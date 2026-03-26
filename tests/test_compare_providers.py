"""
═══════════════════════════════════════════════════════
TEST COMPARE — Chạy cùng 1 prompt qua cả Gemini & OpenAI
và xuất kết quả ra JSON để so sánh chất lượng.
═══════════════════════════════════════════════════════

Cách chạy:
  python -m tests.test_compare_providers

Output:
  - In kết quả từng provider ra terminal theo thứ tự
  - Lưu file JSON vào: tests/results/compare_<timestamp>.json
"""

import sys
import os
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.settings import GEMINI_API_KEY, OPENAI_API_KEY, SUPPORTED_PROVIDERS
from services.prompt_engine import load_system_prompt, build_user_message
from services.gemini_service import call_gemini
from services.openai_service import call_openai

# ──────────────────────────────────────────────
# Kịch bản test — chỉnh ở đây nếu muốn thay prompt
# ──────────────────────────────────────────────
TEST_SCENARIO = {
    "objective": "Cần 4 biểu đồ phân tích hiệu suất doanh thu bán hàng theo quý",
    "num_charts": 4,
    "audience": "Trưởng phòng kinh doanh",
    "bi_tool": "Power BI",
    "columns": [
        {"name": "order_id",        "dtype": "string",   "meaning": "Mã đơn hàng duy nhất"},
        {"name": "order_date",      "dtype": "datetime", "meaning": "Ngày đặt hàng"},
        {"name": "revenue",         "dtype": "float",    "meaning": "Doanh thu đơn hàng (VND)"},
        {"name": "cost",            "dtype": "float",    "meaning": "Giá vốn hàng bán"},
        {"name": "product_category","dtype": "string",   "meaning": "Danh mục sản phẩm"},
        {"name": "region",          "dtype": "string",   "meaning": "Khu vực bán hàng (Bắc/Trung/Nam)"},
        {"name": "customer_type",   "dtype": "string",   "meaning": "Loại khách hàng (Mới/Quay lại)"},
    ],
}

DIVIDER = "=" * 60


def _validate(response: str) -> dict:
    """Kiểm tra output format, trả về dict kết quả check."""
    return {
        "has_tong_quan":    "tổng quan" in response.lower(),
        "has_chart_1":      "chart 1" in response.lower(),
        "has_loi_ket":      (
            "lời kết" in response.lower()
            or "brainstorm" in response.lower()
            or "điều chỉnh" in response.lower()
        ),
        "no_python_code":   (
            "import " not in response
            and "def " not in response
            and "plt." not in response
        ),
    }


def _run_provider(name: str, api_key: str, system_prompt: str, user_message: str) -> dict:
    """
    Gọi 1 provider, đo thời gian, validate output.
    Trả về dict chứa toàn bộ thông tin để lưu JSON.
    """
    model = SUPPORTED_PROVIDERS[name]["model"]
    print(f"\n{'─'*60}")
    print(f"  PROVIDER: {name.upper()}  |  Model: {model}")
    print(f"{'─'*60}")

    start = time.time()
    error = None
    response = ""

    try:
        if name == "gemini":
            response = call_gemini(api_key, system_prompt, user_message)
        else:
            response = call_openai(api_key, system_prompt, user_message)
        elapsed = round(time.time() - start, 2)
        print(f"\n  ✓ Nhận được response ({elapsed}s, {len(response)} chars)\n")
        print(response)
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        error = str(e)
        print(f"\n  ✗ LỖI ({elapsed}s): {error}\n")

    # Validate
    checks = _validate(response) if response else {k: False for k in ["has_tong_quan", "has_chart_1", "has_loi_ket", "no_python_code"]}
    all_passed = all(checks.values())

    print(f"\n  --- VALIDATION ---")
    labels = {
        "has_tong_quan":  "Có 'Tổng quan'",
        "has_chart_1":    "Có 'Chart 1'",
        "has_loi_ket":    "Có 'Lời kết' / câu kết thúc",
        "no_python_code": "KHÔNG có code Python",
    }
    for key, passed in checks.items():
        print(f"  {'✓ PASS' if passed else '✗ FAIL'} — {labels[key]}")
    print(f"\n  → {'✅ ALL PASSED' if all_passed else '⚠️  SOME FAILED'}")

    return {
        "provider":     name,
        "model":        model,
        "elapsed_sec":  elapsed,
        "char_count":   len(response),
        "error":        error,
        "all_passed":   all_passed,
        "checks":       checks,
        "response":     response,
    }


def _save_results(results: list[dict], user_message: str):
    """Lưu kết quả ra file JSON trong tests/results/."""
    output_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"compare_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    payload = {
        "run_at":       datetime.now().isoformat(),
        "scenario":     TEST_SCENARIO,
        "user_message": user_message,
        "results":      results,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return filepath


def run_compare():
    print(DIVIDER)
    print("  COMPARE TEST: Gemini vs OpenAI — cùng 1 user message")
    print(DIVIDER)

    # ── Kiểm tra keys ──
    has_gemini = bool(GEMINI_API_KEY)
    has_openai = bool(OPENAI_API_KEY) and OPENAI_API_KEY != "your-OPENAI_API_KEY"
    print(f"\n  Gemini key : {'✓ có' if has_gemini else '✗ không có — sẽ bỏ qua'}")
    print(f"  OpenAI key : {'✓ có' if has_openai else '✗ không có — sẽ bỏ qua'}")

    if not has_gemini and not has_openai:
        print("\n  ✗ Không có API key nào. Thêm vào file .env rồi thử lại.")
        return

    # ── Build user message (dùng chung cho cả 2) ──
    user_message = build_user_message(
        objective=TEST_SCENARIO["objective"],
        num_charts=TEST_SCENARIO["num_charts"],
        columns_info=TEST_SCENARIO["columns"],
        audience=TEST_SCENARIO["audience"],
        bi_tool=TEST_SCENARIO["bi_tool"],
    )
    print(f"\n  User message: {len(user_message)} chars — dùng chung cho cả 2 provider")

    # ── Chạy lần lượt từng provider ──
    results = []

    if has_gemini:
        gemini_prompt = load_system_prompt("gemini")
        results.append(_run_provider("gemini", GEMINI_API_KEY, gemini_prompt, user_message))

    if has_openai:
        openai_prompt = load_system_prompt("openai")
        results.append(_run_provider("openai", OPENAI_API_KEY, openai_prompt, user_message))

    # ── Tổng kết ──
    print(f"\n{DIVIDER}")
    print("  TỔNG KẾT")
    print(DIVIDER)
    for r in results:
        status = "✅ PASS" if r["all_passed"] else ("✗ ERROR" if r["error"] else "⚠️  FAIL")
        print(f"  {r['provider'].upper():<8} {status}  |  {r['elapsed_sec']}s  |  {r['char_count']} chars")

    # ── Lưu JSON ──
    saved_path = _save_results(results, user_message)
    print(f"\n  💾 Đã lưu kết quả: {saved_path}")
    print(DIVIDER)


if __name__ == "__main__":
    run_compare()
