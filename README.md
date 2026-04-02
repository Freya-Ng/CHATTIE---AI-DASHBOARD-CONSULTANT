# CHATTIE.AI — Dashboard Consultant

> *Instant chart advice for your data.*

**CHATTIE.AI** là chatbot tư vấn dashboard được xây dựng cho Data Analyst và Data Scientist — đặc biệt là những bạn mới bắt đầu. Thay vì mất hàng giờ băn khoăn "nên dùng chart gì?", bạn chỉ cần mô tả dataset và mục tiêu phân tích, chatbot sẽ gợi ý ngay những biểu đồ cụ thể, có công thức tính toán, phù hợp với đối tượng người xem và công cụ BI bạn đang dùng.

Mục tiêu: giúp bạn tạo ra dashboard **chứa nhiều insights hơn** trong **ít thời gian hơn** — và học được tư duy thiết kế dashboard trong quá trình đó.

---

## Giao diện

![Giao diện chính][welcome-screen]

[welcome-screen]: docs/pics/Welcome%20Screen.png

---

## Quick Start

### Dùng luôn — không cần cài đặt

Truy cập **[dashboard-consultant.streamlit.app](https://dashboard-consultant.streamlit.app/)**, nhập API key của bạn (Gemini miễn phí) rồi bắt đầu chat.

Lấy Gemini API key miễn phí tại [aistudio.google.com](https://aistudio.google.com).

---

### Tự chạy local hoặc chỉnh sửa chatbot

**1. Cài đặt**

```bash
git clone https://github.com/Freya-Ng/AI-Dashboard-Consultant.git
cd AI-Dashboard-Consultant
pip install -r requirements.txt
```

**2. Cấu hình API key**

```bash
cp .example-env .env
# Mở .env, điền GEMINI_API_KEY hoặc OPENAI_API_KEY
```

**3. Chạy app**

```bash
streamlit run app.py
```

---

### Test & Fine-tune

Dành cho bạn muốn chỉnh sửa system prompt hoặc đánh giá chất lượng câu trả lời.

```bash
# Kiểm tra kết nối API và format output cơ bản
python -m tests.test_prompt_engine

# So sánh output của Gemini và OpenAI trên cùng một bộ test cases
python -m tests.test_compare_providers

# Convert test_cases.json sang format cho test runner
python -m tests.convert_test_cases

# Chạy toàn bộ test suite (rule-based + LLM-as-Judge)
python -m tests.test_runner

# Chỉ chạy 1 provider
python -m tests.test_runner --provider gemini
python -m tests.test_runner --provider openai

# Chỉ chạy 1 test case hoặc 1 nhóm
python -m tests.test_runner --case TC-A2-001
python -m tests.test_runner --group A

# Dry run — validate test cases, không gọi API
python -m tests.test_runner --dry-run

# Tắt LLM-as-Judge, chỉ dùng rule-based
python -m tests.test_runner --no-judge

# Chỉ chạy các case ưu tiên cao
python -m tests.test_runner --priority High
```

---

## Phases

| Phase | Mô tả | Trạng thái |
|-------|-------|------------|
| **Phase 1** | Foundation — cấu trúc project, kết nối API, test cơ bản | ✅ Done |
| **Phase 2** | System Prompt Iteration — thử 3-5 kịch bản, đo chất lượng, chỉnh prompt | ✅ Done |
| **Phase 3** | UI cơ bản — sidebar, chat display, provider selector, streaming | ✅ Done |
| **Phase 4** | State Management — lịch sử chat, chỉnh sửa từng chart theo turn | 🔄 In progress |

---

## Cấu trúc project

```
AI-Dashboard-Consultant/
│
├── app.py                          ← Entry point — chạy: streamlit run app.py
│
├── config/
│   └── settings.py                 ← Cấu hình provider, model, token limit, đường dẫn prompt
│
├── services/
│   ├── prompt_engine.py            ← Load system prompt từ file template
│   ├── gemini_service.py           ← Gọi Gemini API (google-genai), có streaming & retry
│   ├── openai_service.py           ← Gọi OpenAI API, có streaming
│   └── llm_router.py               ← Điều phối request đến đúng provider
│
├── components/
│   ├── sidebar.py                  ← Sidebar: chọn provider, nhập API key, đổi ngôn ngữ
│   ├── chat_window.py              ← Hiển thị hội thoại, xử lý input, render streaming
│   └── welcome_screen.py          ← Màn hình chào với 4 info card + 3 ví dụ mẫu
│
├── utils/
│   └── state_manager.py            ← CRUD cho st.session_state (messages, provider, key...)
│
├── templates/
│   ├── system_prompt_gemini.txt    ← System prompt riêng cho Gemini
│   ├── system_prompt_gpt.txt       ← System prompt riêng cho GPT
│   └── judge_prompt.txt            ← Prompt dùng để LLM chấm điểm output (Phase 2)
│
├── tests/
│   ├── test_prompt_engine.py       ← Test kết nối API + format output
│   ├── test_compare_providers.py   ← So sánh Gemini vs OpenAI song song
│   ├── test_runner.py              ← Test suite đầy đủ: rule-based + LLM-as-Judge
│   ├── convert_test_cases.py       ← Chuyển test_cases.json sang format test runner
│   ├── test_cases.json             ← Bộ test cases nguồn (~60 kịch bản)
│   └── results/                    ← Output JSON sau mỗi lần chạy (git-ignored)
│
├── docs/
│   └── pics/                       ← Ảnh chụp màn hình app
│
├── assets/
│   └── logo.jpg                    ← Logo hiển thị trên sidebar
│
├── .streamlit/
│   └── config.toml                 ← Theme màu sắc và cấu hình server
│
├── .example-env                    ← Mẫu file .env (copy và điền key thật)
└── requirements.txt                ← Danh sách thư viện cần cài
```

---

## Technology Stack

| Thành phần | Công nghệ |
|------------|-----------|
| UI Framework | [Streamlit](https://streamlit.io/) >= 1.31 |
| LLM — Gemini | [google-genai](https://pypi.org/project/google-genai/) >= 1.0 (thư viện **mới** — không phải `google-generativeai`) |
| LLM — OpenAI | [openai](https://pypi.org/project/openai/) >= 1.40 |
| Env config | python-dotenv |
| Model mặc định | `gemini-2.5-flash` (free) / `gpt-4o-mini` |
| Fallback model | `gemini-2.5-flash-lite` |

> **Lưu ý Gemini Free Tier:** giới hạn 15 requests/phút và có daily quota. Nếu gặp lỗi `429 PerDay`, chờ reset lúc ~2 giờ chiều (giờ VN) hoặc tạo API key mới tại một Google Cloud project khác.

---

## Hướng mở rộng

- **Persona đa dạng** — Tạo thêm các biến thể system prompt với thái độ và phong cách khác nhau (thẳng thắn, hài hước, nghiêm túc...) để phù hợp với từng context làm việc.
- **Upload dữ liệu mẫu** — Cho phép người dùng dán một phần dữ liệu thực (vài dòng CSV) để chatbot hiểu rõ hơn về phân phối và chất lượng data trước khi gợi ý chart.
- **Sinh code chart** — Mở rộng output để chatbot có thể tạo code Python (Plotly, Matplotlib) hoặc DAX/M query tương ứng với từng chart đã gợi ý.
