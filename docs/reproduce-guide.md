# Hướng dẫn Test API Connection

Tài liệu này hướng dẫn cách kiểm tra API sau khi clone repo về máy.

---

## 1. Cài đặt môi trường

```bash
# (Khuyến nghị) Tạo virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

# Cài dependencies
pip install -r requirements.txt
```

---

## 2. Cấu hình API Key

Tạo file `.env` ở thư mục gốc:

```bash
cp .env.example .env
```

Mở `.env` và điền key vào:

```env
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here   # Bỏ trống nếu không dùng OpenAI
```

> **Lấy Gemini API key miễn phí:** https://aistudio.google.com/app/apikey
> **Chỉ cần 1 trong 2 key** — app sẽ tự bỏ qua provider không có key.

---

## 3. Các lệnh test

### Test 1 — Kiểm tra kết nối và luồng hội thoại

```bash
python -m tests.test_prompt_engine
```

Chạy kịch bản hội thoại 3 lượt để xác nhận API hoạt động đúng:

| Lượt | Hành động |
|------|-----------|
| 1 | Gửi metadata (tên cột, mục tiêu) → AI xác nhận lại, chưa gợi ý chart |
| 2 | User confirm → AI gợi ý đầy đủ các charts |
| 3 | User hỏi thêm → AI giải thích chi tiết Chart 1 |

**Kết quả lưu tại:** `tests/results/conversation_YYYYMMDD_HHMMSS.json`

---

### Test 2 — Chạy bộ test cases đa kịch bản

```bash
# Chạy tất cả test cases
python -m tests.test_runner

# Chỉ test Gemini hoặc OpenAI
python -m tests.test_runner --provider gemini
python -m tests.test_runner --provider openai

# Chạy 1 case cụ thể theo ID
python -m tests.test_runner --case TC-A2-001

# Chạy cả nhóm
python -m tests.test_runner --group A
```

Bộ test cases được định nghĩa trong `tests/test_cases.json` và chia thành các nhóm:

| Group | Mô tả |
|-------|--------|
| A | Happy path — input đầy đủ, đúng format |
| B | Thiếu thông tin — AI phải hỏi thêm |
| C | Mâu thuẫn dữ liệu — AI phải cảnh báo |
| D | Edge case — yêu cầu vượt giới hạn |
| E | Người dùng không hợp tác — AI giữ thái độ chuyên nghiệp |

**Kết quả lưu tại:** `tests/results/scenario_report_YYYYMMDD_HHMMSS.json`

---

## 4. Output files

Tất cả kết quả đều nằm trong `tests/results/`:

| Prefix tên file | Sinh ra bởi | Nội dung |
|-----------------|-------------|---------|
| `conversation_` | `test_prompt_engine` | 3-turn conversation, output từng lượt + validation |
| `scenario_report_` | `test_runner` | Nhiều test cases, pass/fail từng check |

---

## 5. Xử lý lỗi thường gặp

### Lỗi 429 — Hết quota

```
429 Resource has been exhausted (quota limit)
```

- **PerMinute:** Chờ 60 giây rồi chạy lại.
- **PerDay (`limit: 0`):** Quota ngày đã hết, chờ reset (~2:00 SA hôm sau giờ VN). Hoặc tạo API key mới ở Google AI Studio với project khác.

### Lỗi 404 — Model không tồn tại

```
404 models/gemini-1.5-flash is not found
```

App dùng `gemini-2.5-flash`. Kiểm tra `config/settings.py` — đảm bảo không có `gemini-1.5-flash`.

### ModuleNotFoundError

```
ModuleNotFoundError: No module named 'google.genai'
```

Chạy lại `pip install -r requirements.txt`. Kiểm tra đang dùng đúng virtual environment.

### API key không được nhận

File `.env` phải đặt ở thư mục gốc (cùng cấp với `app.py`). Không có dấu cách xung quanh dấu `=`.
