"""
Cấu hình trung tâm cho toàn bộ ứng dụng.
Mọi tham số model, giới hạn token, danh sách provider đều nằm ở đây.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# API Keys — đọc từ file .env hoặc st.session_state (khi user nhập trên UI)
# ──────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ──────────────────────────────────────────────
# Danh sách LLM Provider được hỗ trợ
# ──────────────────────────────────────────────
SUPPORTED_PROVIDERS = {
    "gemini": {
        "display_name": "Google Gemini (Free)",
        "model": "gemini-2.5-flash",
        "fallback_model": "gemini-2.0-flash",  # Stable fallback khi 2.5 fail
        "max_output_tokens": 4096,
        "temperature": 0.7,
    },
    "openai": {
        "display_name": "OpenAI GPT",
        "model": "gpt-4o-mini",
        "max_output_tokens": 4096,
        "temperature": 0.5,
    },
}

# ──────────────────────────────────────────────
# Provider mặc định
# ──────────────────────────────────────────────
DEFAULT_PROVIDER = "gemini"

# ──────────────────────────────────────────────
# Đường dẫn tới System Prompt template
# ──────────────────────────────────────────────
SYSTEM_PROMPT_PATHS = {
    "gemini": os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "templates",
        "system_prompt_gemini.txt",
    ),
    "openai": os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "templates",
        "system_prompt_gpt.txt",
    ),
}

# ──────────────────────────────────────────────
# Giới hạn ứng dụng
# ──────────────────────────────────────────────
MAX_CHARTS = 12          # Số chart tối đa cho phép yêu cầu trong 1 lần
MAX_COLUMNS = 50         # Số cột tối đa user có thể nhập
MAX_HISTORY_TURNS = 20   # Số lượt hội thoại lưu trong session
