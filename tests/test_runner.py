"""
═══════════════════════════════════════════════════════════════
TEST RUNNER — Hybrid: Rule-based + Cross LLM-as-Judge
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

Luồng đánh giá (2-pass):
  Pass 1: Rule-based checks (nhanh, miễn phí, deterministic)
          → FAIL ngay nếu rule check thất bại
  Pass 2: Cross LLM-as-Judge (chỉ cho case PASS rule-based)
          → AI đối thủ đánh giá chất lượng ngữ nghĩa sâu
          → 4 chiều × thang 1-5 + criteria pass/fail

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
                        "month", "quarter", "year", "new", "true", "false"}
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
Đánh giá response theo 4 chiều (1-5) và tiêu chí cụ thể.
Trả về CHÍNH XÁC 1 JSON object:
{
  "task_comprehension": <1-5>,
  "response_quality": <1-5>,
  "format_compliance": <1-5>,
  "audience_awareness": <1-5>,
  "criteria_pass": <true/false>,
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

        score_fields = ["task_comprehension", "response_quality",
                        "format_compliance", "audience_awareness"]
        for field in score_fields:
            if field not in result:
                result[field] = 3
            else:
                result[field] = max(1, min(5, int(result[field])))

        if "criteria_pass" not in result:
            result["criteria_pass"] = True
        if "failed_criteria" not in result:
            result["failed_criteria"] = []
        if "reasoning" not in result:
            result["reasoning"] = ""

        result["judge_provider"] = judge_provider
        result["judge_error"] = None
        return result

    except json.JSONDecodeError as e:
        return {
            "task_comprehension": 0, "response_quality": 0,
            "format_compliance": 0, "audience_awareness": 0,
            "criteria_pass": False,
            "failed_criteria": ["Judge JSON parse error"],
            "reasoning": f"JSON parse error: {e}. Raw: {raw_response[:300]}",
            "judge_provider": judge_provider,
            "judge_error": f"JSON parse error: {e}",
        }
    except Exception as e:
        return {
            "task_comprehension": 0, "response_quality": 0,
            "format_compliance": 0, "audience_awareness": 0,
            "criteria_pass": False,
            "failed_criteria": ["Judge API error"],
            "reasoning": str(e),
            "judge_provider": judge_provider,
            "judge_error": str(e),
        }


# ─────────────────────────────────────────────────────────────
# SECTION 3: FINAL VERDICT LOGIC
# ─────────────────────────────────────────────────────────────

SCORE_FIELDS = ["task_comprehension", "response_quality",
                "format_compliance", "audience_awareness"]


def compute_verdict(rule_passed: bool, judge_result: Optional[dict],
                    judge_enabled: bool) -> dict:
    """
    Verdict cuối cùng:
      Rule FAIL                              → FAIL
      Rule PASS + judge OFF                  → PASS
      Rule PASS + judge error                → PASS_WITH_WARNING
      Rule PASS + judge criteria_pass=false  → FAIL
      Rule PASS + judge avg < 3.0            → WARN
      Rule PASS + judge avg >= 3.0           → PASS
    """
    if not rule_passed:
        return {"verdict": "FAIL", "reason": "Rule-based checks failed",
                "judge_avg": None}

    if not judge_enabled or judge_result is None:
        return {"verdict": "PASS", "reason": "Rule-based passed (judge disabled)",
                "judge_avg": None}

    if judge_result.get("judge_error"):
        return {"verdict": "PASS_WITH_WARNING",
                "reason": f"Rule passed, judge error: {judge_result['judge_error'][:60]}",
                "judge_avg": None}

    scores = [judge_result.get(f, 0) for f in SCORE_FIELDS]
    avg = sum(scores) / len(scores) if scores else 0
    criteria_pass = judge_result.get("criteria_pass", True)

    if not criteria_pass:
        failed = judge_result.get("failed_criteria", [])
        return {"verdict": "FAIL",
                "reason": f"Judge criteria failed: {failed[:2]}",
                "judge_avg": round(avg, 2)}

    if avg < 3.0:
        return {"verdict": "WARN",
                "reason": f"Judge avg={avg:.1f} < 3.0 — cần review",
                "judge_avg": round(avg, 2)}

    return {"verdict": "PASS",
            "reason": f"Rule ✓ + Judge avg={avg:.1f}",
            "judge_avg": round(avg, 2)}


# ─────────────────────────────────────────────────────────────
# SECTION 4: CONVERSATION RUNNER — chạy multi-turn
# ─────────────────────────────────────────────────────────────

def run_single_case(test_case: dict, provider: str, api_key: str,
                    judge_enabled: bool = True) -> dict:
    """Chạy 1 test case (multi-turn) + đánh giá hybrid cross-judge."""

    case_id = test_case["id"]
    system_prompt = load_system_prompt(provider)

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
    print(f"  Provider: {provider.upper()} | "
          f"Judge: {judge_prov.upper() if judge_enabled else 'OFF'} | "
          f"Turns: {len(turns)}")

    if not turns:
        print(f"  ⚠  Không có 'turns' trong test case — bỏ qua.")
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
            "judge_provider": None,
            "verdict": "SKIP",
            "verdict_reason": "No 'turns' field in test case",
            "judge_avg": None,
            "rule_all_passed": False,
            "status": "SKIP",
            "total_turns": 0,
            "turns": [],
            "judge_result": None,
            "judge_criteria_used": [],
        }

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

    # PASS 2: Cross LLM-as-Judge
    judge_result = None
    if judge_enabled and all_rule_passed and all_judge_criteria:
        print(f"\n    🧑‍⚖️ Cross-Judge: {judge_prov.upper()} đánh giá {provider.upper()}...")
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
            avg = sum(scores) / len(scores)
            cp = "✓" if judge_result["criteria_pass"] else "✗"
            print(f"    📊 TC={scores[0]} RQ={scores[1]} "
                  f"FC={scores[2]} AA={scores[3]} | avg={avg:.1f} | criteria={cp}")
            if judge_result.get("reasoning"):
                print(f"    💬 {judge_result['reasoning'][:150]}")

    # Verdict
    verdict = compute_verdict(all_rule_passed, judge_result, judge_enabled)
    icons = {"PASS": "🟢", "FAIL": "🔴", "WARN": "🟡", "PASS_WITH_WARNING": "🟠"}
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
        "verdict": verdict["verdict"],
        "verdict_reason": verdict["reason"],
        "judge_avg": verdict["judge_avg"],
        "rule_all_passed": all_rule_passed,
        "status": "PASS" if verdict["verdict"] == "PASS" else "FAIL",
        "total_turns": len(turn_results),
        "turns": turn_results,
        "judge_result": judge_result,
        "judge_criteria_used": all_judge_criteria,
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
    for tc in test_cases:
        case_issues = []
        for field in ["id", "name", "group"]:
            if field not in tc:
                case_issues.append(f"Missing field: {field}")

        has_turns = "turns" in tc and isinstance(tc["turns"], list)
        if not has_turns:
            case_issues.append("Missing 'turns' — test case dùng format cũ, chưa thể chạy tự động")
        else:
            for turn in tc["turns"]:
                if not turn.get("message"):
                    case_issues.append(f"Turn {turn.get('turn', '?')}: empty message")
            real_turns = [t for t in tc["turns"] if not t.get("is_setup")]
            if not real_turns:
                case_issues.append("No non-setup turns!")

        status = "✓" if not case_issues else "✗"
        turns_list = tc.get("turns", [])
        checks_count = sum(len(t.get("checks", {})) for t in turns_list)
        judge_count = sum(len(t.get("judge_criteria", [])) for t in turns_list)
        turns_count = len(turns_list)
        setup_count = sum(1 for t in turns_list if t.get("is_setup"))

        tc_id = tc.get("id", "?")
        print(f"  {status} {tc_id:12} | turns={turns_count} (setup={setup_count}) | "
              f"checks={checks_count} | judge_criteria={judge_count}")

        if case_issues:
            for issue in case_issues:
                print(f"      ⚠  {issue}")
            issues.append({"id": tc_id, "issues": case_issues})

    print(f"\n  Total: {len(test_cases)} cases | Issues: {len(issues)}")
    return issues


# ─────────────────────────────────────────────────────────────
# SECTION 6: REPORT TABLE
# ─────────────────────────────────────────────────────────────

def generate_summary_table(results: list):
    """In bảng tóm tắt trên terminal."""

    print(f"\n{'─' * 80}")
    print(f"{'DETAILED RESULTS':^80}")
    print(f"{'─' * 80}")
    print(f"  {'Case':<13} {'Tested':<8} {'Judge':<8} {'Verdict':<20} "
          f"{'Rule':<5} {'JAvg':<5} {'Reason'}")
    print(f"  {'─' * 75}")

    for r in results:
        rule = "✓" if r["rule_all_passed"] else "✗"
        javg = f"{r['judge_avg']:.1f}" if r["judge_avg"] is not None else "—"
        jp = r.get("judge_provider", "—") or "—"
        print(f"  {r['case_id']:<13} {r['tested_provider']:<8} {jp:<8} "
              f"{r['verdict']:<20} {rule:<5} {javg:<5} "
              f"{r['verdict_reason'][:35]}")

    # Group summary
    print(f"\n{'─' * 80}")
    print(f"{'GROUP SUMMARY':^80}")
    print(f"{'─' * 80}")

    groups = {}
    for r in results:
        key = f"{r['group']}-{r['group_name']}"
        if key not in groups:
            groups[key] = {"total": 0, "pass": 0, "fail": 0, "warn": 0}
        groups[key]["total"] += 1
        v = r["verdict"]
        if v == "PASS":
            groups[key]["pass"] += 1
        elif v == "FAIL":
            groups[key]["fail"] += 1
        elif v != "SKIP":
            groups[key]["warn"] += 1

    print(f"  {'Group':<30} {'Total':>5} {'Pass':>5} {'Fail':>5} "
          f"{'Warn':>5} {'Rate':>6}")
    print(f"  {'─' * 60}")
    for group, s in sorted(groups.items()):
        rate = round(s["pass"] / max(s["total"], 1) * 100)
        print(f"  {group:<30} {s['total']:>5} {s['pass']:>5} {s['fail']:>5} "
              f"{s['warn']:>5} {rate:>5}%")

    # Provider comparison
    print(f"\n{'─' * 80}")
    print(f"{'PROVIDER COMPARISON':^80}")
    print(f"{'─' * 80}")

    providers = {}
    for r in results:
        p = r["tested_provider"]
        if p not in providers:
            providers[p] = {"total": 0, "pass": 0, "fail": 0, "warn": 0,
                            "judge_scores": []}
        providers[p]["total"] += 1
        v = r["verdict"]
        if v == "PASS":
            providers[p]["pass"] += 1
        elif v == "FAIL":
            providers[p]["fail"] += 1
        elif v != "SKIP":
            providers[p]["warn"] += 1
        if r["judge_avg"] is not None:
            providers[p]["judge_scores"].append(r["judge_avg"])

    for p, s in providers.items():
        rate = round(s["pass"] / max(s["total"], 1) * 100)
        avg_j = (sum(s["judge_scores"]) / len(s["judge_scores"])
                 if s["judge_scores"] else 0)
        judged_by = "Gemini" if p == "openai" else "OpenAI"
        print(f"  {p.upper():<10} Pass={s['pass']}/{s['total']} ({rate}%) | "
              f"Fail={s['fail']} Warn={s['warn']} | "
              f"AvgJudge={avg_j:.2f} (judged by {judged_by})")


# ─────────────────────────────────────────────────────────────
# SECTION 7: MAIN — Load cases, run, generate report
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test Runner — Hybrid Rule-based + Cross LLM-as-Judge"
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

    # Load test cases — dùng file đã convert (có turns/checks/judge_criteria)
    cases_path = os.path.join(os.path.dirname(__file__), "test_cases_for_runner.json")
    if not os.path.exists(cases_path):
        print(f"✗ File not found: {cases_path}")
        print(f"  Hãy chạy convert_test_cases.py trước để tạo file này:")
        print(f"  python -m tests.convert_test_cases")
        return

    with open(cases_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support cả flat array [...] lẫn {"test_cases": [...]}
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

    # Judge availability check
    judge_enabled = not args.no_judge
    if judge_enabled and not (OPENAI_API_KEY and GEMINI_API_KEY):
        print("⚠  Cross-judge cần CẢ 2 API keys (OpenAI + Gemini).")
        print("  Chỉ có 1 key → judge sẽ tự chấm (không lý tưởng).")
        print("  Dùng --no-judge để tắt judge nếu muốn.")

    total_runs = len(test_cases) * len(providers)
    print("=" * 65)
    print(f"  TEST RUNNER — HYBRID + CROSS-JUDGE")
    print("=" * 65)
    print(f"  Cases:     {len(test_cases)}")
    print(f"  Providers: {[p[0].upper() for p in providers]}")
    print(f"  Total:     {total_runs} runs")
    print(f"  Judge:     {'CROSS (Gemini↔OpenAI)' if judge_enabled else 'OFF'}")
    print(f"  Started:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    all_results = []
    summary = {"total": 0, "pass": 0, "fail": 0, "warn": 0, "skip": 0}

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
            elif v == "FAIL":
                summary["fail"] += 1
            elif v == "SKIP":
                summary["skip"] += 1
            else:
                summary["warn"] += 1

            time.sleep(3)

    # Generate report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pass_rate = round(summary["pass"] / max(summary["total"], 1) * 100)

    report = {
        "run_at": datetime.now().isoformat(),
        "version": "2.0-cross-judge",
        "config": {
            "providers_tested": [p[0] for p in providers],
            "judge_mode": "cross" if judge_enabled else "disabled",
            "judge_mapping": {
                "openai": "judged_by_gemini",
                "gemini": "judged_by_openai",
            } if judge_enabled else None,
            "total_cases": len(test_cases),
            "total_runs": total_runs,
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

    print(f"\n{'=' * 65}")
    skip_str = f" {summary['skip']}⬜" if summary["skip"] else ""
    print(f"  OVERALL: {summary['pass']}🟢 {summary['fail']}🔴 "
          f"{summary['warn']}🟡{skip_str} / {summary['total']} | {pass_rate}% pass")
    target = "✓ TARGET MET" if pass_rate >= 90 else "✗ BELOW 90% TARGET"
    print(f"  {target}")
    print(f"  Report: {report_path}")
    print(f"{'=' * 65}")

    failed = [r for r in all_results if r["verdict"] == "FAIL"]
    if failed:
        print(f"\n  🔴 FAILED ({len(failed)}):")
        for r in failed:
            print(f"    {r['case_id']} ({r['provider']}): {r['verdict_reason'][:55]}")

    warned = [r for r in all_results if r["verdict"] in ("WARN", "PASS_WITH_WARNING")]
    if warned:
        print(f"\n  🟡 WARNINGS ({len(warned)}):")
        for r in warned:
            print(f"    {r['case_id']} ({r['provider']}): {r['verdict_reason'][:55]}")


if __name__ == "__main__":
    main()
