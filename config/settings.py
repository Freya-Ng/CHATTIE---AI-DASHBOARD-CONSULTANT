import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

SUPPORTED_PROVIDERS = {
    "gemini": {
        "display_name": "Google Gemini (Free)",
        "model": "gemini-2.5-flash",
        "fallback_model": "gemini-2.5-flash-lite",
        "max_output_tokens": 2048,
        "temperature": 0.4,
    },
    "openai": {
        "display_name": "OpenAI GPT",
        "model": "gpt-4o-mini",
        "max_output_tokens": 2048,
        "temperature": 0.4,
    },
}

DEFAULT_PROVIDER = "gemini"

SYSTEM_PROMPT_PATHS = {
    "gemini": os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "system_prompt_gemini.txt"),
    "openai": os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "system_prompt_gpt.txt"),
}
