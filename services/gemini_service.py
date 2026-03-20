"""
Gemini Service — Wrapper gọi Google Gemini API.
Thư viện: google-genai (MỚI). KHÔNG dùng google-generativeai (deprecated).
Có retry cho rate limit per-minute và fallback model.
"""

import time
from google import genai
from google.genai import types
from config.settings import SUPPORTED_PROVIDERS

# Retry config
MAX_RETRIES = 2
RETRY_DELAY = 55  # Gemini yêu cầu chờ ~49s cho per-minute limit


def _is_daily_quota_error(error_str: str) -> bool:
    """Kiểm tra xem lỗi có phải do hết quota NGÀY hay không."""
    return (
        "PerDay" in error_str
        or "PerDayPerProject" in error_str
        or "PerDayPerProjectPerModel" in error_str
        or ("limit: 0" in error_str and "PerDay" in error_str)
    )


def _attempt_call(client, model_name: str, gen_config, user_message: str) -> str:
    """Gọi API 1 lần, retry nếu gặp 429 per-minute (không retry nếu hết quota ngày)."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_message,
                config=gen_config,
            )
            return response.text

        except Exception as e:
            last_error = e
            error_str = str(e)

            if "429" in error_str or "quota" in error_str.lower():
                # Nếu hết quota NGÀY → không retry, báo lỗi rõ ràng
                if _is_daily_quota_error(error_str):
                    raise Exception(
                        f"⛔ Daily quota exhausted for {model_name}. "
                        f"Free tier resets ~2PM Vietnam time (midnight PT). "
                        f"Options: (1) Wait until tomorrow, "
                        f"(2) Create a NEW API key in a NEW Google Cloud project at aistudio.google.com, "
                        f"(3) Use OpenAI provider instead."
                    )
                # Per-minute limit → chờ rồi retry
                print(
                    f"  ⏳ Per-minute rate limit on {model_name} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}). Waiting {RETRY_DELAY}s..."
                )
                time.sleep(RETRY_DELAY)
            else:
                raise

    raise last_error


def call_gemini(
    api_key: str,
    system_prompt: str,
    user_message: str,
) -> str:
    """
    Gọi Gemini API.
    Thử model chính → nếu fail → thử fallback model.

    Raises:
        ValueError: API key trống.
        Exception:  Cả 2 model đều fail (kèm hướng dẫn xử lý).
    """

    if not api_key:
        raise ValueError("Gemini API Key is empty. Please provide a valid key.")

    client = genai.Client(api_key=api_key)
    model_config = SUPPORTED_PROVIDERS["gemini"]

    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=model_config["max_output_tokens"],
        temperature=model_config["temperature"],
    )

    # Thử model chính
    primary = model_config["model"]
    try:
        print(f"  → Trying {primary}...")
        return _attempt_call(client, primary, gen_config, user_message)
    except Exception as primary_err:
        fallback = model_config.get("fallback_model")
        if not fallback:
            raise

        # Thử fallback
        print(f"  ⚠ {primary} failed. Trying fallback: {fallback}...")
        try:
            return _attempt_call(client, fallback, gen_config, user_message)
        except Exception as fallback_err:
            raise Exception(
                f"Both models failed.\n"
                f"  Primary ({primary}): {primary_err}\n"
                f"  Fallback ({fallback}): {fallback_err}\n\n"
                f"💡 Solutions:\n"
                f"  1. Wait until daily quota resets (~2PM VN time)\n"
                f"  2. Create a new API key at aistudio.google.com (new project)\n"
                f"  3. Switch to OpenAI provider"
            )
