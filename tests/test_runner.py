"""
═══════════════════════════════════════════════════════════════
TEST RUNNER V2 — Hybrid: Rule-based + Cross LLM-as-Judge
═══════════════════════════════════════════════════════════════

Cross-Judge: Gemini đánh giá output của GPT, GPT đánh giá output của Gemini.
             → Tránh thiên vị khi AI tự chấm chính mình.

Cách chạy:
  cd ai-dashboard-consultant
  python -m tests.test_runner                         # Test cả 2 providers
  python -m tests.test_runner --provider openai       # Chỉ test OpenAI (judge = Gemini)
  python -m tests.test_runner --provider gemini       # Chỉ test Gemini (judge = OpenAI)
  python -m tests.test_runner --case TC-A2-001        # 1 case cụ thể
  python -m tests.test_runner --group A               # Chạy nhóm A
  python -m tests.test_runner --no-judge              # Tắt LLM-as-Judge (chỉ rule-based)
  python -m tests.test_runner --dry-run               # Validate test cases, không gọi API
  python -m tests.test_runner --priority High         # Chỉ chạy case High priority

Luồng đánh giá (2-pass with judge_override):
  Pass 1: Rule-based checks (nhanh, miễn phí, deterministic)
          → HARD_FAIL ngay nếu rule check thất bại VÀ case không có judge_override
          → Nếu case có judge_override=true → vẫn tiếp tục sang Pass 2
  Pass 2: Cross LLM-as-Judge
          → AI đối thủ đánh giá chất lượng ngữ nghĩa sâu
          → 4 chiều × thang 1-5 + criteria_pass_rate (0.0-1.0)
          → Weighted average + floor checks → 3-tier verdict

Output:
  - Terminal: realtime progress + summary table
  - JSON report: tests/results/scenario_report_YYYYMMDD_HHMMSS.json
"""

import json
import sys
import os
import re
import time
import argparse
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.settings import GEMINI_API_KEY, OPENAI_API_KEY
from services.prompt_engine import load_system_prompt
from services.llm_router import get_consultation


# ─────────────────────────────────────────────────────────────
# JUDGE EVALUATION THRESHOLDS
# ─────────────────────────────────────────────────────────────
# Có thể chuyển sang config/settings.py nếu muốn tách riêng

JUDGE_WEIGHTS = {
    "task_comprehension": 0.30,
    "response_quality": 0.30,
    "format_compliance": 0.20,
    "audience_awareness": 0.20,
}

JUDGE_FLOORS = {
    "task_comprehension": 2,
    "response_quality": 2,
    "format_compliance": 2,
    "audience_awareness": 1,
}

WEIGHTED_AVG_PASS = 3.0
WEIGHTED_AVG_SOFT_FAIL = 2.5
CRITERIA_RATE_PASS = 0.70
CRITERIA_RATE_SOFT_FAIL = 0.50

# Cases mà rule-based quá cứng, cho phép judge quyết định thay
JUDGE_OVERRIDE_CASES = [
    "TC-D-001",   # Turn 2 thiếu keyword "tối đa" nhưng đã giới hạn 6 chart ở turn 1
    "TC-D-003",   # Turn 2 thiếu keyword "6 chart" nhưng trả lời hợp lý
    "TC-G-006",   # Bot hỏi thêm info (đúng) nhưng rule đòi chart ngay
    "TC-G-008",   # Bot hỏi thêm info (đúng) nhưng rule đòi chart ngay
]

# Project-level targets
PROJECT_PASS_RATE_TARGET = 0.80
PROJECT_HARD_FAIL_MAX = 5
PROJECT_WEIGHTED_AVG_TARGET = 3.5

SCORE_FIELDS = ["task_comprehension", "response_quality",
                "format_compliance", "audience_awareness"]


# ─────────────────────────────────────────────────────────────
# SECTION 1: RULE-BASED EVALUATORS
# ─────────────────────────────────────────────────────────────

def evaluate_check(check_name: str, check_config: dict, response: str) -> dict:
    """Đánh giá 1 check rule dựa trên response text."""
    check_type = check_config["type"]
    passed = False
    detail = ""

    response_lower = response.lower()

    if check_type == "not_empty":
        passed = len(response.strip()) > 0
        detail = f"Response length: {len(response)}"

    elif check_type == "contains":
        value = check_config["value"]
        passed = value.lower() in response_lower
        detail = f"Looking for '{value}': {'found' if passed else 'NOT found'}"

    elif check_type == "not_contains":
        value = check_config["value"]
        passed = value.lower() not in response_lower
        detail = f"Should NOT contain '{value}': {'clean' if passed else 'FOUND (bad)'}"

    elif check_type == "contains_any":
        values = check_config["values"]
        found = [v for v in values if v.lower() in response_lower]
        passed = len(found) > 0
        detail = f"Looking for any of {values}: found {found}" if passed else f"NONE found from {values}"

    elif check_type == "not_contains_any":
        values = check_config["values"]
        found = [v for v in values if v.lower() in response_lower]
        passed = len(found) == 0
        detail = f"Should NOT contain {values}: {'clean' if passed else f'FOUND {found} (bad)'}"

    elif check_type == "count_min":
        substring = check_config["substring"]
        min_count = check_config["min"]
        count = response_lower.count(substring.lower())
        passed = count >= min_count
        detail = f"Count '{substring}': {count} (need >= {min_count})"

    elif check_type == "only_columns":
        allowed = check_config["allowed"]
        backtick_cols = re.findall(r'`(\w+)`', response)
        ignore_words = {"sum", "count", "avg", "min", "max", "profit", "total",
                        "cpc", "ctr", "cvr", "roi", "rate", "ratio", "percent",
                        "month", "quarter", "year", "new", "true", "false",
                        "tenure", "profit_margin", "conversion_rate",
                        "revenue", "margin"}
        invalid = [c for c in backtick_cols
                   if c.lower() not in [a.lower() for a in allowed]
                   and c.lower() not in ignore_words]
        passed = len(invalid) == 0
        detail = f"Columns in backticks: {backtick_cols}. Invalid: {invalid}" if invalid else f"All columns valid: {backtick_cols}"

    else:
        detail = f"Unknown check type: {check_type}"
        passed = False

    return {
        "check_name": check_name,
        "type": check_type,
        "passed": passed,
        "detail": detail,
    }


# ─────────────────────────────────────────────────────────────
# SECTION 2: CROSS LLM-AS-JUDGE
# ─────────────────────────────────────────────────────────────

def load_judge_prompt() -> str:
    """Load judge system prompt từ file template."""
    judge_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "templates", "judge_prompt.txt"
    )
    if os.path.exists(judge_path):
        with open(judge_path, "r", encoding="utf-8") as f:
            return f.read()

    print("  ⚠  judge_prompt.txt not found, using fallback prompt")
    return _FALLBACK_JUDGE_PROMPT


_FALLBACK_JUDGE_PROMPT = """Bạn là AI Judge đánh giá chatbot tư vấn Dashboard.
Đánh giá response theo 4 chiều (1-5) và criteria_pass_rate.
Trả về CHÍNH XÁC 1 JSON object:
{
  "task_comprehension": <1-5>,
  "response_quality": <1-5>,
  "format_compliance": <1-5>,
  "audience_awareness": <1-5>,
  "criteria_pass_rate": <0.0-1.0>,
  "criteria_total": <int>,
  "criteria_passed": <int>,
  "failed_criteria": [],
  "reasoning": "..."
}"""


def get_cross_judge_provider(tested_provider: str) -> tuple:
    """
    Cross-judge: trả về (judge_provider, judge_api_key).
    OpenAI tested → Gemini judges, và ngược lại.
    """
    if tested_provider == "openai":
        if GEMINI_API_KEY:
            return ("gemini", GEMINI_API_KEY)
        else:
            print("  ⚠  Cross-judge: Gemini key not found, self-judging with OpenAI")
            return ("openai", OPENAI_API_KEY)
    else:  # gemini
        if OPENAI_API_KEY:
            return ("openai", OPENAI_API_KEY)
        else:
            print("  ⚠  Cross-judge: OpenAI key not found, self-judging with Gemini")
            return ("gemini", GEMINI_API_KEY)


def build_judge_user_prompt(conversation_history: list, judge_criteria: list,
                            case_name: str, expected_behavior: str,
                            test_group: str, test_group_name: str) -> str:
    """Build user prompt gửi cho LLM Judge."""

    conv_lines = []
    for i, entry in enumerate(conversation_history):
        conv_lines.append(f"[USER lượt {i+1}]: {entry['user']}")
        assistant_text = entry['assistant']
        if len(assistant_text) > 3000:
            assistant_text = assistant_text[:3000] + "\n... (truncated)"
        conv_lines.append(f"[BOT lượt {i+1}]: {assistant_text}")
        conv_lines.append("")
    conv_text = "\n".join(conv_lines)

    if judge_criteria:
        criteria_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(judge_criteria))
    else:
        criteria_text = "  (Không có tiêu chí cụ thể — đánh giá tổng quát chất lượng response)"

    return f"""─── TEST CASE ───
Tên: {case_name}
Nhóm: {test_group} — {test_group_name}

─── HÀNH VI MONG ĐỢI ───
{expected_behavior}

─── CUỘC HỘI THOẠI ───
{conv_text}

─── TIÊU CHÍ CỤ THỂ CHO CASE NÀY ───
{criteria_text}

Hãy đánh giá TOÀN BỘ cuộc hội thoại (không chỉ lượt cuối).
Trả về CHÍNH XÁC 1 JSON object theo format đã quy định."""


def _normalize_judge_result(result: dict, judge_criteria: list) -> dict:
    """
    Chuẩn hóa output từ judge — hỗ trợ CẢ format v1 (criteria_pass)
    lẫn format v2 (criteria_pass_rate).
    Đảm bảo output luôn có criteria_pass_rate.
    """
    # Score fields: clamp 1-5, default 3
    for field in SCORE_FIELDS:
        if field not in result:
            result[field] = 3
        else:
            result[field] = max(1, min(5, int(result[field])))

    # Handle criteria — v2 format (criteria_pass_rate)
    if "criteria_pass_rate" in result:
        result["criteria_pass_rate"] = max(0.0, min(1.0, float(result["criteria_pass_rate"])))
        if "criteria_total" not in result:
            result["criteria_total"] = len(judge_criteria) if judge_criteria else 1
        if "criteria_passed" not in result:
            result["criteria_passed"] = round(result["criteria_pass_rate"] * result["criteria_total"])

    # Fallback: v1 format (criteria_pass boolean) → convert to v2
    elif "criteria_pass" in result:
        total = len(judge_criteria) if judge_criteria else 1
        failed = result.get("failed_criteria", [])
        passed_count = max(0, total - len(failed))
        result["criteria_pass_rate"] = round(passed_count / max(total, 1), 2)
        result["criteria_total"] = total
        result["criteria_passed"] = passed_count

    # No criteria info at all
    else:
        result["criteria_pass_rate"] = 1.0
        result["criteria_total"] = len(judge_criteria) if judge_criteria else 0
        result["criteria_passed"] = result["criteria_total"]

    # Ensure other fields exist
    if "failed_criteria" not in result:
        result["failed_criteria"] = []
    if "reasoning" not in result:
        result["reasoning"] = ""

    return result


def call_judge(tested_provider: str,
               conversation_history: list, judge_criteria: list,
               case_name: str, expected_behavior: str,
               test_group: str = "", test_group_name: str = "") -> dict:
    """
    Gọi Cross LLM Judge.
    tested_provider = AI đang được test → judge = AI đối thủ.
    """
    judge_provider, judge_api_key = get_cross_judge_provider(tested_provider)

    judge_system = load_judge_prompt()
    user_prompt = build_judge_user_prompt(
        conversation_history, judge_criteria,
        case_name, expected_behavior,
        test_group, test_group_name,
    )

    raw_response = ""
    try:
        raw_response = get_consultation(
            provider=judge_provider,
            api_key=judge_api_key,
            system_prompt=judge_system,
            user_message=user_prompt,
        )

        cleaned = raw_response.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        cleaned = cleaned.strip()

        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(0)

        result = json.loads(cleaned)
        result = _normalize_judge_result(result, judge_criteria)

        result["judge_provider"] = judge_provider
        result["judge_error"] = None
        return result

    except json.JSONDecodeError as e:
        return {
            "task_comprehension": 0, "response_quality": 0,
            "format_compliance": 0, "audience_awareness": 0,
            "criteria_pass_rate": 0.0,
            "criteria_total": len(judge_criteria) if judge_criteria else 0,
            "criteria_passed": 0,
            "failed_criteria": ["Judge JSON parse error"],
            "reasoning": f"JSON parse error: {e}. Raw: {raw_response[:300]}",
            "judge_provider": judge_provider,
            "judge_error": f"JSON parse error: {e}",
        }
    except Exception as e:
        return {
            "task_comprehension": 0, "response_quality": 0,
            "format_compliance": 0, "audience_awareness": 0,
            "criteria_pass_rate": 0.0,
            "criteria_total": len(judge_criteria) if judge_criteria else 0,
            "criteria_passed": 0,
            "failed_criteria": ["Judge API error"],
            "reasoning": str(e),
            "judge_provider": judge_provider,
            "judge_error": str(e),
        }


# ─────────────────────────────────────────────────────────────
# SECTION 3: FINAL VERDICT LOGIC — 3-TIER
# ─────────────────────────────────────────────────────────────

def compute_weighted_avg(judge_result: dict) -> float:
    """Tính weighted average từ 4 dimension scores."""
    return sum(
        judge_result.get(dim, 0) * weight
        for dim, weight in JUDGE_WEIGHTS.items()
    )


def check_floor_violation(judge_result: dict) -> Optional[str]:
    """
    Kiểm tra hard floor violation.
    Trả về tên dimension bị vi phạm, hoặc None nếu OK.
    """
    for dim, floor in JUDGE_FLOORS.items():
        score = judge_result.get(dim, 0)
        if score < floor:
            return f"{dim}={score} < floor {floor}"
    return None


def compute_verdict(rule_passed: bool, judge_result: Optional[dict],
                    judge_enabled: bool, judge_override: bool = False) -> dict:
    """
    3-tier verdict logic:

    Lớp 1 — Rule-based:
      rule FAIL + no override    → HARD_FAIL
      rule FAIL + override=true  → tiếp tục sang judge (best = SOFT_FAIL)

    Lớp 2 — Judge:
      floor violation            → HARD_FAIL
      avg < 2.5 or rate < 0.50  → HARD_FAIL
      avg >= 3.0 and rate >= 0.70 → PASS (hoặc SOFT_FAIL nếu rule failed + override)
      còn lại                    → SOFT_FAIL
    """
    # ── Lớp 1: Rule-based ──
    if not rule_passed:
        if not judge_override:
            return {
                "verdict": "HARD_FAIL",
                "reason": "Rule-based checks failed",
                "weighted_avg": None,
                "criteria_rate": None,
            }
        # judge_override=True: rule failed nhưng cho judge quyết định
        # Kết quả tốt nhất có thể là SOFT_FAIL (không thể PASS vì rule failed)
        if not judge_enabled or judge_result is None:
            return {
                "verdict": "HARD_FAIL",
                "reason": "Rule failed + judge disabled (override ineffective)",
                "weighted_avg": None,
                "criteria_rate": None,
            }

    # ── Judge disabled hoặc không có result ──
    if not judge_enabled or judge_result is None:
        if rule_passed:
            return {
                "verdict": "PASS",
                "reason": "Rule-based passed (judge disabled)",
                "weighted_avg": None,
                "criteria_rate": None,
            }
        # rule_passed=False nhưng đã qua override check ở trên → không nên tới đây
        # Safety fallback
        return {
            "verdict": "HARD_FAIL",
            "reason": "Rule failed + no judge available",
            "weighted_avg": None,
            "criteria_rate": None,
        }

    # Từ đây judge_result chắc chắn không phải None

    # ── Judge error ──
    if judge_result.get("judge_error"):
        if rule_passed:
            return {
                "verdict": "SOFT_FAIL",
                "reason": f"Rule passed, judge error: {judge_result['judge_error'][:60]}",
                "weighted_avg": None,
                "criteria_rate": None,
            }
        else:
            return {
                "verdict": "HARD_FAIL",
                "reason": f"Rule failed + judge error: {judge_result['judge_error'][:60]}",
                "weighted_avg": None,
                "criteria_rate": None,
            }

    # ── Lớp 2: Judge evaluation ──
    weighted_avg = compute_weighted_avg(judge_result)
    criteria_rate = judge_result.get("criteria_pass_rate", 1.0)

    # Check 1: Hard floor violation
    floor_violation = check_floor_violation(judge_result)
    if floor_violation:
        return {
            "verdict": "HARD_FAIL",
            "reason": f"Floor violation: {floor_violation}",
            "weighted_avg": round(weighted_avg, 2),
            "criteria_rate": round(criteria_rate, 2),
        }

    # Check 2: Very low scores → HARD_FAIL
    if weighted_avg < WEIGHTED_AVG_SOFT_FAIL or criteria_rate < CRITERIA_RATE_SOFT_FAIL:
        return {
            "verdict": "HARD_FAIL",
            "reason": f"avg={weighted_avg:.2f}<{WEIGHTED_AVG_SOFT_FAIL} or rate={criteria_rate:.0%}<{CRITERIA_RATE_SOFT_FAIL:.0%}",
            "weighted_avg": round(weighted_avg, 2),
            "criteria_rate": round(criteria_rate, 2),
        }

    # Check 3: Good enough for PASS?
    if weighted_avg >= WEIGHTED_AVG_PASS and criteria_rate >= CRITERIA_RATE_PASS:
        if rule_passed:
            return {
                "verdict": "PASS",
                "reason": f"Rule ✓ + avg={weighted_avg:.2f} + rate={criteria_rate:.0%}",
                "weighted_avg": round(weighted_avg, 2),
                "criteria_rate": round(criteria_rate, 2),
            }
        else:
            # Rule failed + override → judge says OK → best is SOFT_FAIL
            return {
                "verdict": "SOFT_FAIL",
                "reason": f"Rule ✗ (override) + Judge OK: avg={weighted_avg:.2f} rate={criteria_rate:.0%}",
                "weighted_avg": round(weighted_avg, 2),
                "criteria_rate": round(criteria_rate, 2),
            }

    # Check 4: In between → SOFT_FAIL
    return {
        "verdict": "SOFT_FAIL",
        "reason": f"avg={weighted_avg:.2f} or rate={criteria_rate:.0%} below threshold",
        "weighted_avg": round(weighted_avg, 2),
        "criteria_rate": round(criteria_rate, 2),
    }


# ─────────────────────────────────────────────────────────────
# SECTION 4: CONVERSATION RUNNER — chạy multi-turn
# ─────────────────────────────────────────────────────────────

def run_single_case(test_case: dict, provider: str, api_key: str,
                    judge_enabled: bool = True) -> dict:
    """Chạy 1 test case (multi-turn) + đánh giá hybrid cross-judge."""

    case_id = test_case["id"]
    system_prompt = load_system_prompt(provider)

    # Check judge_override — từ test case hoặc từ danh sách global
    judge_override = (
        test_case.get("judge_override", False)
        or case_id in JUDGE_OVERRIDE_CASES
    )

    conversation_history = []
    turn_results = []
    all_rule_passed = True
    all_judge_criteria = []
    last_expected = ""

    judge_prov, _ = get_cross_judge_provider(provider)

    group_name = test_case.get("group_name", test_case.get("group", ""))
    domain = test_case.get("domain", "")
    turns = test_case.get("turns", [])

    print(f"\n  {'─' * 60}")
    print(f"  {case_id} — {test_case['name']}")
    print(f"  Group: {test_case['group']} ({group_name}) | Domain: {domain}")
    override_tag = " | ⚡ judge_override" if judge_override else ""
    print(f"  Provider: {provider.upper()} | "
          f"Judge: {judge_prov.upper() if judge_enabled else 'OFF'} | "
          f"Turns: {len(turns)}{override_tag}")

    if not turns:
        print(f"  ⚠  Không có 'turns' trong test case — bỏ qua.")
        return _skip_result(test_case, provider)

    for turn in turns:
        turn_num = turn["turn"]
        user_msg = turn["message"]
        is_setup = turn.get("is_setup", False)

        tag = "SETUP" if is_setup else f"Turn {turn_num}"
        print(f"\n    [{tag}] Sending ({len(user_msg)} chars)...")

        # Build full context cho multi-turn
        if conversation_history:
            full_context = ""
            for prev in conversation_history:
                full_context += f"[User trước đó]: {prev['user']}\n[AI trước đó]: {prev['assistant']}\n\n"
            full_context += f"[User hiện tại]: {user_msg}"
        else:
            full_context = user_msg

        # Gọi API
        start_time = time.time()
        try:
            response = get_consultation(
                provider=provider,
                api_key=api_key,
                system_prompt=system_prompt,
                user_message=full_context,
            )
            elapsed = round(time.time() - start_time, 2)
            error = None
        except Exception as e:
            response = ""
            elapsed = round(time.time() - start_time, 2)
            error = str(e)
            print(f"    ✗ API Error: {error}")

        conversation_history.append({
            "user": user_msg,
            "assistant": response,
        })

        # PASS 1: Rule-based checks
        check_results = []
        turn_passed = True

        if error is None and "checks" in turn:
            for check_name, check_config in turn["checks"].items():
                result = evaluate_check(check_name, check_config, response)
                check_results.append(result)
                status = "✓" if result["passed"] else "✗"
                print(f"    {status} {check_name}: {result['detail']}")
                if not result["passed"]:
                    turn_passed = False
                    all_rule_passed = False
        elif error:
            turn_passed = False
            all_rule_passed = False

        # Collect judge criteria
        if turn.get("judge_criteria"):
            all_judge_criteria.extend(turn["judge_criteria"])

        last_expected = turn.get("expected_behavior", last_expected)

        failed_checks = [c for c in check_results if not c["passed"]]
        turn_results.append({
            "turn": turn_num,
            "is_setup": is_setup,
            "user_message": user_msg,
            "context_sent_to_api": full_context,
            "expected_behavior": turn.get("expected_behavior", ""),
            "response": response,
            "response_length": len(response),
            "elapsed_sec": elapsed,
            "error": error,
            "checks": check_results,
            "failed_checks": failed_checks,
            "turn_passed": turn_passed,
        })

        if turn_num < len(test_case["turns"]):
            time.sleep(2)

    # ── Determine whether to run judge ──
    # Run judge if: (a) judge enabled AND (b) rule passed OR judge_override
    should_run_judge = (
        judge_enabled
        and all_judge_criteria
        and (all_rule_passed or judge_override)
    )

    # PASS 2: Cross LLM-as-Judge
    judge_result = None
    if should_run_judge:
        override_note = " (override: rule failed)" if not all_rule_passed else ""
        print(f"\n    🧑‍⚖️ Cross-Judge: {judge_prov.upper()} đánh giá "
              f"{provider.upper()}{override_note}...")
        judge_result = call_judge(
            tested_provider=provider,
            conversation_history=conversation_history,
            judge_criteria=all_judge_criteria,
            case_name=test_case["name"],
            expected_behavior=last_expected,
            test_group=test_case.get("group", ""),
            test_group_name=test_case.get("group_name", ""),
        )

        if judge_result.get("judge_error"):
            print(f"    ⚠  Judge error: {judge_result['judge_error']}")
        else:
            scores = [judge_result[f] for f in SCORE_FIELDS]
            w_avg = compute_weighted_avg(judge_result)
            c_rate = judge_result.get("criteria_pass_rate", 0)
            c_total = judge_result.get("criteria_total", 0)
            c_passed = judge_result.get("criteria_passed", 0)
            print(f"    📊 TC={scores[0]} RQ={scores[1]} FC={scores[2]} AA={scores[3]}")
            print(f"    📊 W.Avg={w_avg:.2f} | Criteria={c_passed}/{c_total} ({c_rate:.0%})")
            if judge_result.get("failed_criteria"):
                print(f"    ❌ Failed: {judge_result['failed_criteria'][:3]}")
            if judge_result.get("reasoning"):
                print(f"    💬 {judge_result['reasoning'][:150]}")

    # Verdict
    verdict = compute_verdict(
        rule_passed=all_rule_passed,
        judge_result=judge_result,
        judge_enabled=judge_enabled,
        judge_override=judge_override,
    )

    icons = {"PASS": "🟢", "HARD_FAIL": "🔴", "SOFT_FAIL": "🟡"}
    print(f"\n  {icons.get(verdict['verdict'], '⚪')} {case_id}: "
          f"{verdict['verdict']} — {verdict['reason']}")

    return {
        "case_id": case_id,
        "case_name": test_case["name"],
        "group": test_case.get("group", ""),
        "group_name": group_name,
        "domain": domain,
        "priority": test_case.get("priority", ""),
        "description": test_case.get("description", test_case.get("notes", "")),
        "preconditions": test_case.get("preconditions", ""),
        "provider": provider,
        "tested_provider": provider,
        "system_prompt_provider": provider,
        "judge_provider": judge_result["judge_provider"] if judge_result else None,
        "judge_override": judge_override,
        "verdict": verdict["verdict"],
        "verdict_reason": verdict["reason"],
        "weighted_avg": verdict["weighted_avg"],
        "criteria_rate": verdict["criteria_rate"],
        "rule_all_passed": all_rule_passed,
        "total_turns": len(turn_results),
        "turns": turn_results,
        "judge_result": judge_result,
        "judge_criteria_used": all_judge_criteria,
    }


def _skip_result(test_case: dict, provider: str) -> dict:
    """Helper: tạo result cho case bị skip."""
    return {
        "case_id": test_case["id"],
        "case_name": test_case["name"],
        "group": test_case.get("group", ""),
        "group_name": test_case.get("group_name", ""),
        "domain": test_case.get("domain", ""),
        "priority": test_case.get("priority", ""),
        "description": test_case.get("description", ""),
        "preconditions": test_case.get("preconditions", ""),
        "provider": provider,
        "tested_provider": provider,
        "system_prompt_provider": provider,
        "judge_provider": None,
        "judge_override": False,
        "verdict": "SKIP",
        "verdict_reason": "No 'turns' field in test case",
        "weighted_avg": None,
        "criteria_rate": None,
        "rule_all_passed": False,
        "total_turns": 0,
        "turns": [],
        "judge_result": None,
        "judge_criteria_used": [],
    }


# ─────────────────────────────────────────────────────────────
# SECTION 5: DRY RUN
# ─────────────────────────────────────────────────────────────

def dry_run(test_cases: list):
    """Validate test case format mà không gọi API."""
    print(f"\n{'=' * 60}")
    print(f"DRY RUN — Validating {len(test_cases)} test cases")
    print(f"{'=' * 60}")

    issues = []
    override_count = 0
    for tc in test_cases:
        case_issues = []
        for field in ["id", "name", "group"]:
            if field not in tc:
                case_issues.append(f"Missing field: {field}")

        has_turns = "turns" in tc and isinstance(tc["turns"], list)
        if not has_turns:
            case_issues.append("Missing 'turns' — test case dùng format cũ")
        else:
            for turn in tc["turns"]:
                if not turn.get("message"):
                    case_issues.append(f"Turn {turn.get('turn', '?')}: empty message")
            real_turns = [t for t in tc["turns"] if not t.get("is_setup")]
            if not real_turns:
                case_issues.append("No non-setup turns!")

        tc_id = tc.get("id", "?")
        has_override = tc.get("judge_override", False) or tc_id in JUDGE_OVERRIDE_CASES
        if has_override:
            override_count += 1

        status = "✓" if not case_issues else "✗"
        turns_list = tc.get("turns", [])
        checks_count = sum(len(t.get("checks", {})) for t in turns_list)
        judge_count = sum(len(t.get("judge_criteria", [])) for t in turns_list)
        turns_count = len(turns_list)
        setup_count = sum(1 for t in turns_list if t.get("is_setup"))
        override_tag = " ⚡OVR" if has_override else ""

        print(f"  {status} {tc_id:12} | turns={turns_count} (setup={setup_count}) | "
              f"checks={checks_count} | judge={judge_count}{override_tag}")

        if case_issues:
            for issue in case_issues:
                print(f"      ⚠  {issue}")
            issues.append({"id": tc_id, "issues": case_issues})

    print(f"\n  Total: {len(test_cases)} cases | Issues: {len(issues)} | "
          f"Judge overrides: {override_count}")
    return issues


# ─────────────────────────────────────────────────────────────
# SECTION 6: REPORT TABLE
# ─────────────────────────────────────────────────────────────

def generate_summary_table(results: list):
    """In bảng tóm tắt trên terminal."""

    # ── Detailed results ──
    print(f"\n{'─' * 90}")
    print(f"{'DETAILED RESULTS':^90}")
    print(f"{'─' * 90}")
    print(f"  {'Case':<13} {'Tested':<8} {'Judge':<8} {'Verdict':<12} "
          f"{'Rule':<5} {'WAvg':<6} {'CRate':<6} {'Reason'}")
    print(f"  {'─' * 85}")

    for r in results:
        rule = "✓" if r["rule_all_passed"] else "✗"
        wavg = f"{r['weighted_avg']:.2f}" if r.get("weighted_avg") is not None else "—"
        crate = f"{r['criteria_rate']:.0%}" if r.get("criteria_rate") is not None else "—"
        jp = r.get("judge_provider", "—") or "—"
        ovr = "⚡" if r.get("judge_override") else ""
        print(f"  {r['case_id']:<13} {r['tested_provider']:<8} {jp:<8} "
              f"{r['verdict']:<12} {rule}{ovr:<4} {wavg:<6} {crate:<6} "
              f"{r['verdict_reason'][:30]}")

    # ── Group summary ──
    print(f"\n{'─' * 90}")
    print(f"{'GROUP SUMMARY':^90}")
    print(f"{'─' * 90}")

    groups = {}
    for r in results:
        key = f"{r['group']}-{r['group_name']}"
        if key not in groups:
            groups[key] = {"total": 0, "pass": 0, "hard_fail": 0, "soft_fail": 0,
                           "skip": 0, "wavg_scores": []}
        groups[key]["total"] += 1
        v = r["verdict"]
        if v == "PASS":
            groups[key]["pass"] += 1
        elif v == "HARD_FAIL":
            groups[key]["hard_fail"] += 1
        elif v == "SOFT_FAIL":
            groups[key]["soft_fail"] += 1
        elif v == "SKIP":
            groups[key]["skip"] += 1
        if r.get("weighted_avg") is not None:
            groups[key]["wavg_scores"].append(r["weighted_avg"])

    print(f"  {'Group':<30} {'Tot':>4} {'Pass':>5} {'Hard':>5} "
          f"{'Soft':>5} {'Rate':>6} {'AvgW':>6}")
    print(f"  {'─' * 65}")
    for group, s in sorted(groups.items()):
        rate = round(s["pass"] / max(s["total"], 1) * 100)
        avg_w = (sum(s["wavg_scores"]) / len(s["wavg_scores"])
                 if s["wavg_scores"] else 0)
        print(f"  {group:<30} {s['total']:>4} {s['pass']:>5} "
              f"{s['hard_fail']:>5} {s['soft_fail']:>5} "
              f"{rate:>5}% {avg_w:>5.2f}")

    # ── Provider comparison ──
    print(f"\n{'─' * 90}")
    print(f"{'PROVIDER COMPARISON':^90}")
    print(f"{'─' * 90}")

    providers = {}
    for r in results:
        p = r["tested_provider"]
        if p not in providers:
            providers[p] = {"total": 0, "pass": 0, "hard_fail": 0, "soft_fail": 0,
                            "wavg_scores": [], "crate_scores": []}
        providers[p]["total"] += 1
        v = r["verdict"]
        if v == "PASS":
            providers[p]["pass"] += 1
        elif v == "HARD_FAIL":
            providers[p]["hard_fail"] += 1
        elif v == "SOFT_FAIL":
            providers[p]["soft_fail"] += 1
        if r.get("weighted_avg") is not None:
            providers[p]["wavg_scores"].append(r["weighted_avg"])
        if r.get("criteria_rate") is not None:
            providers[p]["crate_scores"].append(r["criteria_rate"])

    for p, s in providers.items():
        rate = round(s["pass"] / max(s["total"], 1) * 100)
        avg_w = (sum(s["wavg_scores"]) / len(s["wavg_scores"])
                 if s["wavg_scores"] else 0)
        avg_c = (sum(s["crate_scores"]) / len(s["crate_scores"])
                 if s["crate_scores"] else 0)
        judged_by = "Gemini" if p == "openai" else "OpenAI"
        print(f"  {p.upper():<10} Pass={s['pass']}/{s['total']} ({rate}%) | "
              f"Hard={s['hard_fail']} Soft={s['soft_fail']} | "
              f"W.Avg={avg_w:.2f} CRate={avg_c:.0%} (judged by {judged_by})")

    # ── Project targets ──
    print(f"\n{'─' * 90}")
    print(f"{'PROJECT TARGETS':^90}")
    print(f"{'─' * 90}")

    total_pass = sum(s["pass"] for s in providers.values())
    total_all = sum(s["total"] for s in providers.values())
    total_hard = sum(s["hard_fail"] for s in providers.values())
    all_wavg = []
    for s in providers.values():
        all_wavg.extend(s["wavg_scores"])
    project_wavg = sum(all_wavg) / len(all_wavg) if all_wavg else 0
    pass_rate = total_pass / max(total_all, 1)

    targets = [
        (f"Pass rate >= {PROJECT_PASS_RATE_TARGET:.0%}",
         f"{pass_rate:.0%}", pass_rate >= PROJECT_PASS_RATE_TARGET),
        (f"Hard fails <= {PROJECT_HARD_FAIL_MAX}",
         str(total_hard), total_hard <= PROJECT_HARD_FAIL_MAX),
        (f"W.Avg >= {PROJECT_WEIGHTED_AVG_TARGET}",
         f"{project_wavg:.2f}", project_wavg >= PROJECT_WEIGHTED_AVG_TARGET),
    ]

    # Check group E (guardrails)
    group_e = [r for r in results if r["group"] == "E"]
    if group_e:
        e_pass = sum(1 for r in group_e if r["verdict"] == "PASS")
        e_total = len(group_e)
        e_rate = e_pass / max(e_total, 1)
        targets.append(
            (f"Group E (Guardrails) = 100%",
             f"{e_pass}/{e_total} ({e_rate:.0%})", e_rate >= 1.0)
        )

    for desc, val, met in targets:
        icon = "✅" if met else "❌"
        print(f"  {icon} {desc}: {val}")


# ─────────────────────────────────────────────────────────────
# SECTION 7: MAIN — Load cases, run, generate report
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test Runner V2 — Hybrid Rule-based + Cross LLM-as-Judge (3-tier)"
    )
    parser.add_argument("--provider", choices=["openai", "gemini", "both"], default="both")
    parser.add_argument("--case", type=str, help="Run specific case ID (e.g. TC-A2-001)")
    parser.add_argument("--group", type=str, help="Run specific group (e.g. A, B, C)")
    parser.add_argument("--no-judge", action="store_true",
                        help="Tắt LLM-as-Judge (chỉ dùng rule-based checks)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate test cases mà không gọi API")
    parser.add_argument("--priority", choices=["High", "Medium", "Low"],
                        help="Chỉ chạy cases theo priority")
    args = parser.parse_args()

    # Load test cases
    cases_path = os.path.join(os.path.dirname(__file__), "test_cases_for_runner.json")
    if not os.path.exists(cases_path):
        print(f"✗ File not found: {cases_path}")
        print(f"  Hãy chạy convert_test_cases.py trước để tạo file này:")
        print(f"  python -m tests.convert_test_cases")
        return

    with open(cases_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if isinstance(data, list):
        test_cases = data
    else:
        test_cases = data.get("test_cases", [])

    # Filter
    if args.case:
        test_cases = [tc for tc in test_cases if tc["id"] == args.case]
        if not test_cases:
            print(f"✗ Case '{args.case}' not found.")
            return
    elif args.group:
        test_cases = [tc for tc in test_cases if tc["group"] == args.group.upper()]
        if not test_cases:
            print(f"✗ No cases found in group '{args.group}'.")
            return

    if args.priority:
        test_cases = [tc for tc in test_cases if tc.get("priority") == args.priority]
        if not test_cases:
            print(f"✗ No cases found with priority '{args.priority}'.")
            return

    # Dry run
    if args.dry_run:
        dry_run(test_cases)
        return

    # Determine providers
    providers = []
    if args.provider in ("openai", "both"):
        if OPENAI_API_KEY:
            providers.append(("openai", OPENAI_API_KEY))
        else:
            print("⚠ OpenAI API key not found, skipping.")
    if args.provider in ("gemini", "both"):
        if GEMINI_API_KEY:
            providers.append(("gemini", GEMINI_API_KEY))
        else:
            print("⚠ Gemini API key not found, skipping.")

    if not providers:
        print("✗ No valid API keys found. Check your .env file.")
        return
    
    judge_enabled = not args.no_judge
    if judge_enabled and not (OPENAI_API_KEY and GEMINI_API_KEY):
        print("⚠  Cross-judge cần CẢ 2 API keys (OpenAI + Gemini).")
        print("  Chỉ có 1 key → judge sẽ tự chấm (không lý tưởng).")
        print("  Dùng --no-judge để tắt judge nếu muốn.")

    # Count overrides
    override_count = sum(
        1 for tc in test_cases
        if tc.get("judge_override", False) or tc["id"] in JUDGE_OVERRIDE_CASES
    )

    total_runs = len(test_cases) * len(providers)
    print("=" * 65)
    print(f"  TEST RUNNER V2 — HYBRID + CROSS-JUDGE (3-TIER)")
    print("=" * 65)
    print(f"  Cases:      {len(test_cases)} ({override_count} with judge_override)")
    print(f"  Providers:  {[p[0].upper() for p in providers]}")
    print(f"  Total runs: {total_runs}")
    print(f"  Judge:      {'CROSS (Gemini↔OpenAI)' if judge_enabled else 'OFF'}")
    print(f"  Verdicts:   PASS 🟢 | SOFT_FAIL 🟡 | HARD_FAIL 🔴")
    print(f"  Targets:    Pass≥{PROJECT_PASS_RATE_TARGET:.0%} | "
          f"HardFail≤{PROJECT_HARD_FAIL_MAX} | "
          f"W.Avg≥{PROJECT_WEIGHTED_AVG_TARGET}")
    print(f"  Started:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    all_results = []
    summary = {"total": 0, "pass": 0, "hard_fail": 0, "soft_fail": 0, "skip": 0}

    for provider_name, api_key in providers:
        print(f"\n{'═' * 65}")
        judge_name = "Gemini" if provider_name == "openai" else "OpenAI"
        print(f"  TESTING: {provider_name.upper()}  |  JUDGE: "
              f"{judge_name.upper() if judge_enabled else 'OFF'}")
        print(f"{'═' * 65}")

        for tc in test_cases:
            result = run_single_case(
                test_case=tc,
                provider=provider_name,
                api_key=api_key,
                judge_enabled=judge_enabled,
            )
            all_results.append(result)
            summary["total"] += 1
            v = result["verdict"]
            if v == "PASS":
                summary["pass"] += 1
            elif v == "HARD_FAIL":
                summary["hard_fail"] += 1
            elif v == "SOFT_FAIL":
                summary["soft_fail"] += 1
            elif v == "SKIP":
                summary["skip"] += 1
                
            time.sleep(3)

    # Generate report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pass_rate = round(summary["pass"] / max(summary["total"], 1) * 100)

    report = {
        "run_at": datetime.now().isoformat(),
        "version": "2.1-cross-judge-3tier",
        "config": {
            "providers_tested": [p[0] for p in providers],
            "judge_mode": "cross" if judge_enabled else "disabled",
            "judge_mapping": {
                "openai": "judged_by_gemini",
                "gemini": "judged_by_openai",
            } if judge_enabled else None,
            "total_cases": len(test_cases),
            "total_runs": total_runs,
            "judge_override_cases": [
                tc["id"] for tc in test_cases
                if tc.get("judge_override", False) or tc["id"] in JUDGE_OVERRIDE_CASES
            ],
            "thresholds": {
                "weighted_avg_pass": WEIGHTED_AVG_PASS,
                "weighted_avg_soft_fail": WEIGHTED_AVG_SOFT_FAIL,
                "criteria_rate_pass": CRITERIA_RATE_PASS,
                "criteria_rate_soft_fail": CRITERIA_RATE_SOFT_FAIL,
                "judge_weights": JUDGE_WEIGHTS,
                "judge_floors": JUDGE_FLOORS,
            },
        },
        "summary": summary,
        "pass_rate": f"{summary['pass']}/{summary['total']} ({pass_rate}%)",
        "results": all_results,
    }

    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    report_path = os.path.join(results_dir, f"scenario_report_{timestamp}.json")

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Print summary table
    generate_summary_table(all_results)

    # Overall
    print(f"\n{'=' * 65}")
    skip_str = f" {summary['skip']}⬜" if summary["skip"] else ""
    print(f"  OVERALL: {summary['pass']}🟢 {summary['hard_fail']}🔴 "
          f"{summary['soft_fail']}🟡{skip_str} / {summary['total']} | {pass_rate}% pass")

    target_met = pass_rate >= (PROJECT_PASS_RATE_TARGET * 100)
    target_str = (f"✓ TARGET MET (≥{PROJECT_PASS_RATE_TARGET:.0%})"
                  if target_met
                  else f"✗ BELOW {PROJECT_PASS_RATE_TARGET:.0%} TARGET")
    print(f"  {target_str}")
    print(f"  Report: {report_path}")
    print(f"{'=' * 65}")

    # List failures
    hard_fails = [r for r in all_results if r["verdict"] == "HARD_FAIL"]
    if hard_fails:
        print(f"\n  🔴 HARD_FAIL ({len(hard_fails)}) — fix these first:")
        for r in hard_fails:
            ovr = " ⚡override" if r.get("judge_override") else ""
            print(f"    {r['case_id']} ({r['provider']}): "
                  f"{r['verdict_reason'][:50]}{ovr}")

    soft_fails = [r for r in all_results if r["verdict"] == "SOFT_FAIL"]
    if soft_fails:
        print(f"\n  🟡 SOFT_FAIL ({len(soft_fails)}) — review these:")
        for r in soft_fails:
            print(f"    {r['case_id']} ({r['provider']}): "
                  f"{r['verdict_reason'][:50]}")


if __name__ == "__main__":
    main()
    