import time
from google import genai  # type: ignore
from google.genai import types  # type: ignore
from config.settings import SUPPORTED_PROVIDERS

MAX_RETRIES = 2
RETRY_DELAY = 55


def _get_config():
    cfg = SUPPORTED_PROVIDERS["gemini"]
    return cfg, types.GenerateContentConfig(
        system_instruction=None,  # set per-call
        max_output_tokens=cfg["max_output_tokens"],
        temperature=cfg["temperature"],
    )


def call_gemini(api_key, system_prompt, user_message):
    if not api_key:
        raise ValueError("Gemini API Key is empty.")

    client = genai.Client(api_key=api_key)
    cfg = SUPPORTED_PROVIDERS["gemini"]
    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=cfg["max_output_tokens"],
        temperature=cfg["temperature"],
    )

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=cfg["model"], contents=user_message, config=gen_config,
            )
            return resp.text
        except Exception as e:
            last_err = e
            if "429" in str(e):
                time.sleep(RETRY_DELAY)
            else:
                raise

    if last_err:
        raise last_err
    raise Exception("Gemini API failed.")


def call_gemini_stream(api_key, system_prompt, user_message):
    if not api_key:
        raise ValueError("Gemini API Key is empty.")

    client = genai.Client(api_key=api_key)
    cfg = SUPPORTED_PROVIDERS["gemini"]
    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=cfg["max_output_tokens"],
        temperature=cfg["temperature"],
    )

    response = client.models.generate_content_stream(
        model=cfg["model"], contents=user_message, config=gen_config,
    )

    for chunk in response:
        if chunk.text:
            yield chunk.text
