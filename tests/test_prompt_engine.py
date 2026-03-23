"""
═══════════════════════════════════════════════════════════════
TEST PHASE 1 — Multi-provider · 3-turn conversation
═══════════════════════════════════════════════════════════════

Chạy:
    python -m tests.test_prompt_engine

Kịch bản hội thoại (3 lượt):
  Lượt 1 — User gửi metadata + mục tiêu
            → AI xác nhận lại những gì đã hiểu, hỏi nếu còn thiếu
  Lượt 2 — User confirm AI hiểu đúng
            → AI đưa ra gợi ý charts đầy đủ (đây mới là lúc recommend)
  Lượt 3 — User yêu cầu giải thích thêm Chart 1
            → AI giải thích chi tiết Chart 1

Providers: Gemini và OpenAI, chạy lần lượt, cùng 1 kịch bản
Output: terminal + tests/results/test_<timestamp>.json
═══════════════════════════════════════════════════════════════
"""

import sys
import os
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import google.genai as genai
from google.genai import types as genai_types
from openai import OpenAI

from config.settings import GEMINI_API_KEY, OPENAI_API_KEY, SUPPORTED_PROVIDERS
from services.prompt_engine import load_system_prompt, build_user_message

# ─────────────────────────────────────────────────────────────
# Kịch bản test (3 lượt)
# ─────────────────────────────────────────────────────────────
TEST_COLUMNS = [
    {"name": "order_id",         "dtype": "string",   "meaning": "Mã đơn hàng duy nhất"},
    {"name": "order_date",       "dtype": "datetime", "meaning": "Ngày đặt hàng"},
    {"name": "revenue",          "dtype": "float",    "meaning": "Doanh thu đơn hàng (VND)"},
    {"name": "cost",             "dtype": "float",    "meaning": "Giá vốn hàng bán"},
    {"name": "product_category", "dtype": "string",   "meaning": "Danh mục sản phẩm"},
    {"name": "region",           "dtype": "string",   "meaning": "Khu vực bán hàng (Bắc/Trung/Nam)"},
    {"name": "customer_type",    "dtype": "string",   "meaning": "Loại khách hàng (Mới/Quay lại)"},
]

# Lượt 1: User gửi metadata — AI sẽ confirm lại, KHÔNG recommend chart ngay
TURN_1_OBJECTIVE = "Cần 4 biểu đồ phân tích hiệu suất doanh thu bán hàng theo quý"

# Lượt 2: User confirm AI hiểu đúng → lúc này AI mới recommend charts
TURN_2_CONFIRM = (
    "Đúng rồi, bạn đã hiểu đúng ý tôi. "
    "Hãy tiến hành gợi ý 4 biểu đồ phù hợp nhất cho dashboard này."
)

# Lượt 3: User hỏi thêm về Chart 1 cụ thể
TURN_3_DETAIL = (
    "Tôi muốn hiểu rõ hơn về Chart 1 bạn vừa gợi ý. "
    "Hãy giải thích cách đọc biểu đồ đó và tại sao nó phù hợp với mục tiêu của tôi."
)

CONVERSATION_SCRIPT = [
    {"turn": 1, "label": "Gửi metadata → AI xác nhận hiểu biết"},
    {"turn": 2, "label": "User confirm → AI recommend charts"},
    {"turn": 3, "label": "User hỏi thêm → AI giải thích Chart 1"},
]

DIVIDER     = "=" * 65
SUB_DIVIDER = "─" * 65


# ─────────────────────────────────────────────────────────────
# Validation từng lượt
# ─────────────────────────────────────────────────────────────
def _validate_turn1(text: str) -> dict[str, bool]:
    """Lượt 1: AI nên xác nhận hiểu biết, CHƯA đưa chart đầy đủ."""
    t = text.lower()
    return {
        "AI phản hồi (có nội dung)":       len(text.strip()) > 50,
        "AI không recommend chart ngay":    "chart 1" not in t and "biểu đồ 1" not in t,
        "KHÔNG có code Python":             "import " not in text and "def " not in text,
    }


def _validate_turn2(text: str) -> dict[str, bool]:
    """Lượt 2: AI phải recommend đủ charts."""
    t = text.lower()
    return {
        "Có 'Chart 1'":                    "chart 1" in t or "biểu đồ 1" in t,
        "Có 'Chart 2'":                    "chart 2" in t or "biểu đồ 2" in t,
        "Có 'Lời kết' / câu kết thúc":    (
            "lời kết" in t or "brainstorm" in t
            or "điều chỉnh" in t or "phản hồi" in t
        ),
        "KHÔNG có code Python":            "import " not in text and "def " not in text,
    }


def _validate_turn3(text: str) -> dict[str, bool]:
    """Lượt 3: AI giải thích Chart 1 chi tiết."""
    t = text.lower()
    return {
        "Đề cập đến Chart 1":   (
            "chart 1" in t or "biểu đồ 1" in t or "biểu đồ đầu tiên" in t
        ),
        "Có giải thích (>100 chars)": len(text.strip()) > 100,
        "KHÔNG có code Python":  "import " not in text and "def " not in text,
    }


VALIDATORS = [_validate_turn1, _validate_turn2, _validate_turn3]


def _print_validation(checks: dict[str, bool]) -> bool:
    all_passed = True
    for name, passed in checks.items():
        print(f"    {'✓ PASS' if passed else '✗ FAIL'} — {name}")
        if not passed:
            all_passed = False
    return all_passed


# ─────────────────────────────────────────────────────────────
# Gemini — multi-turn dùng Chat session
# ─────────────────────────────────────────────────────────────
def _run_gemini(system_prompt: str, messages: list[str]) -> list[dict]:
    cfg      = SUPPORTED_PROVIDERS["gemini"]
    client   = genai.Client(api_key=GEMINI_API_KEY)
    primary  = cfg["model"]
    fallback = cfg.get("fallback_model")

    gen_config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=cfg["max_output_tokens"],
        temperature=cfg["temperature"],
    )

    model_used = primary
    try:
        chat = client.chats.create(model=primary, config=gen_config)
    except Exception:
        if not fallback:
            raise
        print(f"  ⚠ {primary} unavailable → fallback: {fallback}...")
        chat = client.chats.create(model=fallback, config=gen_config)
        model_used = fallback

    print(f"  Model: {model_used}")
    return _run_turns(
        send_fn=lambda msg: chat.send_message(msg).text,
        messages=messages,
    )


# ─────────────────────────────────────────────────────────────
# OpenAI — multi-turn dùng messages array
# ─────────────────────────────────────────────────────────────
def _run_openai(system_prompt: str, messages: list[str]) -> list[dict]:
    cfg    = SUPPORTED_PROVIDERS["openai"]
    client = OpenAI(api_key=OPENAI_API_KEY)
    model  = cfg["model"]
    history = [{"role": "system", "content": system_prompt}]

    print(f"  Model: {model}")

    def send_fn(msg: str) -> str:
        history.append({"role": "user", "content": msg})
        resp = client.chat.completions.create(
            model=model,
            messages=history,
            max_tokens=cfg["max_output_tokens"],
            temperature=cfg["temperature"],
        )
        text = resp.choices[0].message.content
        history.append({"role": "assistant", "content": text})
        return text

    return _run_turns(send_fn=send_fn, messages=messages)


# ─────────────────────────────────────────────────────────────
# Chạy các lượt hội thoại (dùng chung cho cả 2 provider)
# ─────────────────────────────────────────────────────────────
def _run_turns(send_fn, messages: list[str]) -> list[dict]:
    results = []
    for i, (msg, meta, validate_fn) in enumerate(
        zip(messages, CONVERSATION_SCRIPT, VALIDATORS), start=1
    ):
        label = meta["label"]
        print(f"\n  [{i}/3] {label}")
        print(f"  User: \"{msg[:100]}{'...' if len(msg) > 100 else ''}\"")
        t0 = time.time()
        try:
            text    = send_fn(msg)
            elapsed = round(time.time() - t0, 2)
            print(f"\n  AI ({elapsed}s · {len(text)} chars):\n")
            print(text)
            print()
            checks = validate_fn(text)
            print(f"  Validation:")
            passed = _print_validation(checks)
            results.append({
                "turn": i, "label": label,
                "user_message": msg,
                "elapsed_sec": elapsed, "char_count": len(text),
                "all_passed": passed, "checks": checks,
                "response": text, "error": None,
            })
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            err = str(e)
            print(f"  ✗ LỖI ({elapsed}s): {err}")
            results.append({
                "turn": i, "label": label,
                "user_message": msg,
                "elapsed_sec": elapsed, "char_count": 0,
                "all_passed": False, "checks": {},
                "response": "", "error": err,
            })
    return results


# ─────────────────────────────────────────────────────────────
# Lưu JSON
# ─────────────────────────────────────────────────────────────
def _save_json(all_results: list[dict]) -> str:
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath  = os.path.join(out_dir, f"conversation_{timestamp}.json")
    payload = {
        "run_at":    datetime.now().isoformat(),
        "test_case": "Phân tích doanh thu bán hàng — 3-turn conversation",
        "providers": all_results,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filepath


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
def run_test():
    print(DIVIDER)
    print("  TEST: 3-turn conversation · Gemini + OpenAI")
    print(DIVIDER)

    has_gemini = bool(GEMINI_API_KEY)
    has_openai = bool(OPENAI_API_KEY) and OPENAI_API_KEY != "your-OPENAI_API_KEY"
    print(f"\n  Gemini key : {'✓ có' if has_gemini else '✗ không có — bỏ qua'}")
    print(f"  OpenAI key : {'✓ có' if has_openai else '✗ không có — bỏ qua'}")

    if not has_gemini and not has_openai:
        print("\n  ✗ Không có API key nào. Thêm vào .env rồi thử lại.")
        return

    # Build turn 1 message (dùng chung)
    turn1_msg = build_user_message(
        objective=TURN_1_OBJECTIVE,
        num_charts=4,
        columns_info=TEST_COLUMNS,
        audience="Trưởng phòng kinh doanh",
        bi_tool="Power BI",
    )
    user_messages = [turn1_msg, TURN_2_CONFIRM, TURN_3_DETAIL]

    print(f"\n  Kịch bản:")
    for meta in CONVERSATION_SCRIPT:
        print(f"    Lượt {meta['turn']}: {meta['label']}")

    all_results = []

    # ── Gemini ──
    if has_gemini:
        print(f"\n{DIVIDER}")
        print("  PROVIDER: GEMINI")
        print(DIVIDER)
        try:
            turns = _run_gemini(load_system_prompt("gemini"), user_messages)
            all_results.append({"provider": "gemini", "turns": turns})
        except Exception as e:
            print(f"  ✗ Gemini thất bại: {e}")
            all_results.append({"provider": "gemini", "turns": [], "fatal_error": str(e)})

    # ── OpenAI ──
    if has_openai:
        print(f"\n{DIVIDER}")
        print("  PROVIDER: OPENAI")
        print(DIVIDER)
        try:
            turns = _run_openai(load_system_prompt("openai"), user_messages)
            all_results.append({"provider": "openai", "turns": turns})
        except Exception as e:
            print(f"  ✗ OpenAI thất bại: {e}")
            all_results.append({"provider": "openai", "turns": [], "fatal_error": str(e)})

    # ── Tổng kết ──
    print(f"\n{DIVIDER}")
    print("  TỔNG KẾT")
    print(DIVIDER)
    overall_pass = True
    for r in all_results:
        if r.get("fatal_error"):
            print(f"  {r['provider'].upper():<8} ✗ FATAL — {r['fatal_error'][:60]}")
            overall_pass = False
            continue
        for t in r["turns"]:
            status = "✓ PASS" if t["all_passed"] else "✗ FAIL"
            err    = f" ← {t['error'][:50]}..." if t["error"] else ""
            print(
                f"  {r['provider'].upper():<8} "
                f"Lượt {t['turn']} — {status}  "
                f"{t['elapsed_sec']}s  {t['char_count']} chars{err}"
            )
            if not t["all_passed"]:
                overall_pass = False

    print()
    print(f"  {'✅ ALL TESTS PASSED' if overall_pass else '⚠️  MỘT SỐ TEST THẤT BẠI — xem chi tiết ở trên'}")

    saved = _save_json(all_results)
    print(f"\n  💾 Kết quả: {saved}")
    print(DIVIDER)


if __name__ == "__main__":
    run_test()
