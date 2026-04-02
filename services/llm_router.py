from services.gemini_service import call_gemini, call_gemini_stream
from services.openai_service import call_openai, call_openai_stream


def get_consultation(provider, api_key, system_prompt, user_message):
    if provider == "gemini":
        return call_gemini(api_key, system_prompt, user_message)
    elif provider == "openai":
        return call_openai(api_key, system_prompt, user_message)
    raise ValueError(f"Provider '{provider}' not supported.")


def get_consultation_stream(provider, api_key, system_prompt, user_message):
    """Returns a generator for streaming, or None if not supported."""
    try:
        if provider == "gemini":
            return call_gemini_stream(api_key, system_prompt, user_message)
        elif provider == "openai":
            return call_openai_stream(api_key, system_prompt, user_message)
    except Exception:
        return None
    return None
