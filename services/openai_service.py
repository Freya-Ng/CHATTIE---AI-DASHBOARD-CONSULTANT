from openai import OpenAI
from config.settings import SUPPORTED_PROVIDERS


def call_openai(api_key, system_prompt, user_message):
    if not api_key:
        raise ValueError("OpenAI API Key is empty.")

    client = OpenAI(api_key=api_key)
    cfg = SUPPORTED_PROVIDERS["openai"]

    resp = client.chat.completions.create(
        model=cfg["model"],
        max_tokens=cfg["max_output_tokens"],
        temperature=cfg["temperature"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return resp.choices[0].message.content or ""


def call_openai_stream(api_key, system_prompt, user_message):
    if not api_key:
        raise ValueError("OpenAI API Key is empty.")

    client = OpenAI(api_key=api_key)
    cfg = SUPPORTED_PROVIDERS["openai"]

    stream = client.chat.completions.create(
        model=cfg["model"],
        max_tokens=cfg["max_output_tokens"],
        temperature=cfg["temperature"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
