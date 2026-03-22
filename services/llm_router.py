"""
LLM Router — Factory Pattern chọn provider phù hợp.
Đây là điểm duy nhất mà app.py hoặc test cần gọi.
"""

from services.gemini_service import call_gemini
from services.openai_service import call_openai


def get_consultation(
    provider: str,
    api_key: str,
    system_prompt: str,
    user_message: str,
) -> str:
    """
    Điều hướng request đến đúng LLM provider.

    Args:
        provider:      "gemini" hoặc "openai"
        api_key:       API key tương ứng
        system_prompt: System prompt đã load
        user_message:  User message đã build

    Returns:
        Chuỗi text tư vấn từ LLM.

    Raises:
        ValueError: Nếu provider không được hỗ trợ.
    """

    if provider == "gemini":
        return call_gemini(api_key, system_prompt, user_message)
    elif provider == "openai":
        return call_openai(api_key, system_prompt, user_message)
    else:
        raise ValueError(
            f"Provider '{provider}' is not supported. "
            f"Choose 'gemini' or 'openai'."
        )


def get_consultation_auto(
    system_prompt: str,
    user_message: str,
    gemini_key: str = "",
    openai_key: str = "",
    preferred: str = "gemini",
) -> tuple[str, str]:
    """
    Tự động chọn provider dựa trên key có sẵn.
    Thử provider ưu tiên trước, nếu fail thì fallback sang provider còn lại.

    Args:
        system_prompt: System prompt đã load
        user_message:  User message đã build
        gemini_key:    Gemini API key (có thể trống)
        openai_key:    OpenAI API key (có thể trống)
        preferred:     Provider ưu tiên ("gemini" hoặc "openai")

    Returns:
        Tuple (response_text, provider_used)

    Raises:
        Exception: Nếu tất cả provider đều fail hoặc không có key nào.
    """
    # Xác định thứ tự thử
    providers = []
    if preferred == "gemini":
        if gemini_key:
            providers.append(("gemini", gemini_key))
        if openai_key:
            providers.append(("openai", openai_key))
    else:
        if openai_key:
            providers.append(("openai", openai_key))
        if gemini_key:
            providers.append(("gemini", gemini_key))

    if not providers:
        raise Exception(
            "Không tìm thấy API key nào. "
            "Vui lòng thêm GEMINI_API_KEY hoặc OPENAI_API_KEY vào file .env"
        )

    errors = []
    for provider, key in providers:
        print(f"  → Thử provider: {provider}...")
        try:
            result = get_consultation(provider, key, system_prompt, user_message)
            print(f"  ✓ {provider} thành công!")
            return result, provider
        except Exception as e:
            print(f"  ✗ {provider} thất bại: {e}")
            errors.append(f"{provider}: {e}")
            if len(providers) > 1:
                next_provider = [p for p, _ in providers if p != provider]
                if next_provider:
                    print(f"  → Chuyển sang fallback: {next_provider[0]}...")

    raise Exception(
        "Tất cả provider đều thất bại:\n" + "\n".join(f"  - {e}" for e in errors)
    )
