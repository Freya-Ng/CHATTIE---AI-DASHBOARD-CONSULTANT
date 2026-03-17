# AI Dashboard Consultant

Ứng dụng Streamlit tư vấn thiết kế Dashboard bằng AI.
Nhập metadata (tên cột, kiểu dữ liệu, mục tiêu) → nhận gợi ý biểu đồ có cấu trúc.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
# Sửa GEMINI_API_KEY trong .env
python -m tests.test_prompt_engine
```

## Providers
- **Gemini** (free): `gemini-2.0-flash` / `gemini-2.0-flash-lite`
- **OpenAI**: `gpt-4o-mini` (cần API key trả phí)
