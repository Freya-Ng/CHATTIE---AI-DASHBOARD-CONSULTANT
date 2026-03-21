"""
OpenAI Service — Wrapper gọi OpenAI API.
Cùng interface với gemini_service: nhận prompt, trả text.
"""

from openai import OpenAI
from config.settings import SUPPORTED_PROVIDERS


def call_openai(
    api_key: str,
    system_prompt: str,
    user_message: str,
) -> str:
    """
    Gọi OpenAI API và trả về response dạng text.

    Raises:
        ValueError: Nếu API key trống.
        Exception:  Nếu API call thất bại.
    """

    if not api_key:
        raise ValueError("OpenAI API Key is empty. Please provide a valid key.")

    client = OpenAI(api_key=api_key)
    model_config = SUPPORTED_PROVIDERS["openai"]

    response = client.chat.completions.create(
        model=model_config["model"],
        max_tokens=model_config["max_output_tokens"],
        temperature=model_config["temperature"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    return response.choices[0].message.content
