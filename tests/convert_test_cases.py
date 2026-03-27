"""
═══════════════════════════════════════════════════════════════
CONVERTER: Chuyển 62 test cases sang format tương thích test_runner.py
═══════════════════════════════════════════════════════════════

Input:  test_cases.json (format hiện tại)
Output: test_cases.json (format test_runner.py cần)

Mỗi test case output sẽ có:
  - turns[]: mỗi turn có message + checks (rule-based) + judge_criteria (LLM-as-Judge)
  - Precondition cases: tự inject setup turn (Happy Path input)
  - Group mapping: "Happy Path" → "A", "Missing Info" → "B", ...
"""

import json
import re
import sys
import os

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

GROUP_MAP = {
    "Happy Path": "A",
    "Missing Info": "B",
    "Bad Quality Input": "C",
    "Over Capacity": "D",
    "Abnormal Behavior": "E",
    "Multi-turn": "F",
    "Diverse Input Format": "G",
    "Opposing Feedback": "H",
    "Edge Cases": "I",
    "BI Tool Constraints": "J",
    "Graceful Exit": "K",
}

# Domain inference từ tên hoặc notes
DOMAIN_KEYWORDS = {
    "doanh thu": "Sales",
    "kinh doanh": "Sales",
    "marketing": "Marketing",
    "quảng cáo": "Marketing",
    "nhân sự": "HR",
    "nghỉ việc": "HR",
    "y tế": "Healthcare",
    "lâm sàng": "Healthcare",
    "khảo sát": "Survey",
    "hài lòng": "Survey",
    "tài chính": "Finance",
    "giáo dục": "Education",
    "logistics": "Logistics",
    "vận chuyển": "Logistics",
    "thương mại điện tử": "E-commerce",
    "ecommerce": "E-commerce",
    "IoT": "IoT",
    "cảm biến": "IoT",
    "nhiệt độ": "IoT",
    "game": "Gaming",
    "sản xuất": "Manufacturing",
}

# ─── Precondition setup messages ───
# Dùng cho cases cần "đã hoàn thành Happy Path" trước đó
SETUP_HAPPY_PATH_4CHART = (
    "Tôi muốn 4 biểu đồ phân tích doanh thu bán hàng. "
    "Data gồm 6 cột: order_date (datetime — ngày đặt), product_name (string — tên sản phẩm), "
    "category (string — danh mục), quantity (int — số lượng), unit_price (float — đơn giá), "
    "revenue (float — doanh thu). Người xem: Trưởng phòng kinh doanh. Công cụ: Power BI."
)

SETUP_HAPPY_PATH_3CHART = (
    "Tôi muốn 3 biểu đồ phân tích doanh thu. "
    "Data gồm 5 cột: order_date (datetime — ngày đặt), product (string — sản phẩm), "
    "revenue (float — doanh thu), region (string — vùng miền), quantity (int — số lượng). "
    "Người xem: Trưởng phòng kinh doanh. Công cụ: Power BI."
)

SETUP_GENERIC = (
    "Tôi muốn 3 biểu đồ phân tích doanh thu. "
    "Data gồm 4 cột: date (datetime — ngày), product (string — sản phẩm), "
    "revenue (float — doanh thu), region (string — vùng miền). "
    "Người xem: Trưởng phòng. Công cụ: Power BI."
)


# ─────────────────────────────────────────────
# PARSER: Extract user turns from specific_input
# ─────────────────────────────────────────────

def parse_specific_input(text: str) -> dict:
    """
    Parse specific_input thành dict {turn_number: message}.
    Format: "Turn 1: 'message1' | Turn 3: 'message2'"
    Xử lý edge case: nội dung message có chứa ký tự '|' (VD: table data)
    """
    turns = {}

    # Strategy: split by "Turn N:" pattern, not by "|"
    # Find all "Turn N:" positions
    pattern = r"Turn\s+(\d+)\s*:"
    matches = list(re.finditer(pattern, text))

    for i, match in enumerate(matches):
        turn_num = int(match.group(1))
        start = match.end()
        # End at next "Turn N:" or end of string
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        raw_msg = text[start:end].strip()

        # Remove trailing " |" separator
        raw_msg = re.sub(r'\s*\|\s*$', '', raw_msg)

        # Remove wrapping quotes (single or double)
        raw_msg = raw_msg.strip()
        if (raw_msg.startswith("'") and raw_msg.endswith("'")) or \
           (raw_msg.startswith('"') and raw_msg.endswith('"')):
            raw_msg = raw_msg[1:-1]

        turns[turn_num] = raw_msg.strip()

    return turns


# ─────────────────────────────────────────────
# CRITERIA → RULE-BASED CHECKS MAPPING
# ─────────────────────────────────────────────

def criteria_to_checks(criteria_list: list, case_id: str, specific_input: str) -> tuple:
    """
    Chuyển pass_fail_criteria thành:
    - rule_checks: dict cho test_runner (nhanh, deterministic)
    - judge_criteria: list cho LLM-as-Judge (semantic, sâu)

    Returns: (rule_checks, judge_criteria)
    """
    rule_checks = {}
    judge_criteria = []

    for i, criterion in enumerate(criteria_list):
        crit_lower = criterion.lower()
        check_name = f"check_{i+1}"

        # ═══ RULE 1: Không sinh code ═══
        if "không sinh code" in crit_lower or "không viết code" in crit_lower:
            rule_checks["no_code"] = {
                "type": "not_contains_any",
                "values": ["```python", "```r", "```sql", "```js", "import ", "def ", "SELECT ", "CREATE TABLE"],
                "criteria_text": criterion,
            }

        # ═══ RULE 2: Đếm số chart ═══
        elif "đúng" in crit_lower and "chart" in crit_lower:
            match = re.search(r'(\d+)\s*chart', crit_lower)
            if match:
                num = int(match.group(1))
                rule_checks["chart_count"] = {
                    "type": "count_min",
                    "substring": "Chart",
                    "min": num,
                    "criteria_text": criterion,
                }

        # ═══ RULE 3: Format chuẩn "Tổng tôi gợi ý X chart" ═══
        elif "tổng tôi gợi ý" in crit_lower or "format output đúng chuẩn" in crit_lower:
            rule_checks["format_standard"] = {
                "type": "contains_any",
                "values": ["tổng tôi gợi ý", "Tổng tôi gợi ý", "gợi ý", "chart"],
                "criteria_text": criterion,
            }

        # ═══ RULE 4: Câu hỏi xác nhận ═══
        elif "câu hỏi xác nhận" in crit_lower or "hỏi xác nhận" in crit_lower or \
             "chỉnh sửa gì không" in crit_lower or "câu hỏi mở cho chỉnh sửa" in crit_lower:
            rule_checks["has_confirmation_q"] = {
                "type": "contains_any",
                "values": ["chỉnh sửa", "điều chỉnh", "thay đổi", "ý kiến", "phản hồi", "hài lòng"],
                "criteria_text": criterion,
            }

        # ═══ RULE 5: Có feature engineering ═══
        elif "feature engineering" in crit_lower:
            rule_checks["has_feature_eng"] = {
                "type": "contains_any",
                "values": ["công thức", "Công thức", "feature engineering", "tính toán", "= "],
                "criteria_text": criterion,
            }
            # Also add to judge for quality evaluation
            judge_criteria.append(criterion)

        # ═══ RULE 6: Đủ thành phần mỗi chart ═══
        elif "đủ" in crit_lower and ("thành phần" in crit_lower or "tên" in crit_lower):
            rule_checks["chart_components"] = {
                "type": "contains_any",
                "values": ["Dạng chart", "dạng chart", "Chart type", "Loại biểu đồ",
                           "Bar", "Line", "Pie", "Scatter", "Heatmap", "Table",
                           "Stacked", "Grouped", "Treemap", "Funnel", "Donut", "Area",
                           "Waterfall", "KPI Card", "Gauge", "Box Plot", "Histogram"],
                "criteria_text": criterion,
            }

        # ═══ RULE 7: Bot từ chối / nhận ra giới hạn ═══
        elif "bot từ chối" in crit_lower or "bot không" in crit_lower.replace("không ", "không "):
            if "10 chart" in crit_lower or "tạo quá" in crit_lower:
                rule_checks["reject_overcapacity"] = {
                    "type": "contains_any",
                    "values": ["tối đa", "giới hạn", "không thể", "6 chart", "quá nhiều", "giảm", "đề xuất"],
                    "criteria_text": criterion,
                }
            elif "bịa" in crit_lower or "tự tạo" in crit_lower:
                # Can't fully verify with rule-based, send to judge
                judge_criteria.append(criterion)
            else:
                judge_criteria.append(criterion)

        # ═══ RULE 8: Bot hỏi lại thông tin thiếu ═══
        elif "hỏi lại" in crit_lower or "hỏi thêm" in crit_lower or "hỏi bổ sung" in crit_lower:
            rule_checks[f"asks_for_info_{i}"] = {
                "type": "contains_any",
                "values": ["?", "cho tôi biết", "cung cấp", "bạn có thể", "thông tin",
                           "cho mình biết", "vui lòng", "hãy cung cấp", "bổ sung"],
                "criteria_text": criterion,
            }

        # ═══ RULE 9: Không phản ứng tiêu cực ═══
        elif "không phản ứng tiêu cực" in crit_lower or "chuyên nghiệp" in crit_lower:
            rule_checks["professional_tone"] = {
                "type": "not_contains_any",
                "values": ["ngu", "mày", "thô lỗ", "khó chịu", "bực mình", "tức giận"],
                "criteria_text": criterion,
            }
            judge_criteria.append(criterion)

        # ═══ RULE 10: Bot dừng lại / chào tạm biệt ═══
        elif "dừng lại" in crit_lower or "tạm biệt" in crit_lower or "kết thúc" in crit_lower:
            rule_checks[f"graceful_exit_{i}"] = {
                "type": "contains_any",
                "values": ["tạm biệt", "chào", "cảm ơn", "hẹn gặp", "chúc", "quay lại",
                           "sẵn sàng", "hỗ trợ", "bye", "giúp đỡ"],
                "criteria_text": criterion,
            }

        # ═══ RULE 11: Bot nhận ra format input (CSV, table, etc.) ═══
        elif "nhận ra" in crit_lower or "nhận diện" in crit_lower:
            judge_criteria.append(criterion)

        # ═══ RULE 12: Sankey / tool-specific constraints ═══
        elif "sankey" in crit_lower or "gds" in crit_lower or "không hỗ trợ" in crit_lower:
            judge_criteria.append(criterion)

        # ═══ RULE 13: Reset / không tham chiếu cũ ═══
        elif "reset" in crit_lower or "không tham chiếu" in crit_lower:
            judge_criteria.append(criterion)

        # ═══ DEFAULT: Semantic → gửi cho LLM Judge ═══
        else:
            judge_criteria.append(criterion)

    return rule_checks, judge_criteria


# ─────────────────────────────────────────────
# DOMAIN INFERENCE
# ─────────────────────────────────────────────

def infer_domain(case: dict) -> str:
    """Đoán domain từ tên case, notes, specific_input."""
    text = f"{case['name']} {case['notes']} {case['specific_input']}".lower()
    for keyword, domain in DOMAIN_KEYWORDS.items():
        if keyword.lower() in text:
            return domain
    return "General"


# ─────────────────────────────────────────────
# BUILD SETUP TURN (for precondition cases)
# ─────────────────────────────────────────────

def get_setup_message(preconditions: str, case_id: str) -> str:
    """Tạo setup message dựa trên preconditions."""
    prec_lower = preconditions.lower()
    if "4 chart" in prec_lower:
        return SETUP_HAPPY_PATH_4CHART
    elif "3 chart" in prec_lower:
        return SETUP_HAPPY_PATH_3CHART
    elif "happy path" in prec_lower or "đã hoàn thành" in prec_lower:
        return SETUP_HAPPY_PATH_4CHART  # Default to 4 chart
    elif "nhiều lượt" in prec_lower or "2-3 lượt" in prec_lower:
        return SETUP_GENERIC
    elif "đã gợi ý chart" in prec_lower or "đã có ít nhất 1 lượt" in prec_lower:
        return SETUP_GENERIC
    return SETUP_GENERIC


# ─────────────────────────────────────────────
# MAIN CONVERTER
# ─────────────────────────────────────────────

def convert_case(case: dict) -> dict:
    """Chuyển 1 test case sang format mới."""

    group_code = GROUP_MAP.get(case["group"], "X")
    domain = infer_domain(case)

    # Parse user turns from specific_input
    user_turns = parse_specific_input(case["specific_input"])

    # Parse expected_output per turn
    expected_per_turn = parse_specific_input(case["expected_output"])

    # Check if this case needs precondition setup
    needs_setup = (
        "Đã" in case["preconditions"] or
        "precondition" in case["preconditions"].lower()
    )

    # Find the minimum turn number from user_turns
    if user_turns:
        min_turn = min(user_turns.keys())
    else:
        min_turn = 1

    # Build turns array
    turns = []
    turn_counter = 0

    # === SETUP TURN (if needed) ===
    if needs_setup and min_turn > 1:
        turn_counter += 1
        setup_msg = get_setup_message(case["preconditions"], case["id"])
        turns.append({
            "turn": turn_counter,
            "message": setup_msg,
            "is_setup": True,
            "expected_behavior": f"Precondition setup: {case['preconditions']}",
            "checks": {
                "setup_not_empty": {"type": "not_empty"}
            },
            "judge_criteria": [],
        })

    # === USER TURNS (actual test messages) ===
    # Generate rule checks and judge criteria from pass_fail_criteria
    rule_checks, judge_criteria = criteria_to_checks(
        case["pass_fail_criteria"],
        case["id"],
        case["specific_input"],
    )

    # ─── Classify checks for smart distribution ───
    # Chart-output checks: belong on the turn whose response contains chart output
    chart_output_checks = {}
    defensive_checks = {}
    ask_info_checks = {}
    exit_checks = {}
    other_checks = {}

    for name, cfg in rule_checks.items():
        if name in ("chart_count", "chart_components", "format_standard",
                     "has_confirmation_q", "has_feature_eng"):
            chart_output_checks[name] = cfg
        elif name in ("no_code", "professional_tone"):
            defensive_checks[name] = cfg
        elif name.startswith("asks_for_info"):
            ask_info_checks[name] = cfg
        elif name.startswith("graceful_exit") or name.startswith("reject_overcapacity"):
            exit_checks[name] = cfg
        else:
            other_checks[name] = cfg

    # ─── Determine which turn should get chart checks ───
    # Groups where Turn 1 triggers chart output directly:
    chart_on_first = group_code in ("A", "G", "I", "J")
    # Groups where the LAST turn triggers chart output:
    chart_on_last = group_code in ("B",)
    # Groups where Turn 1 triggers a special response (reject, ask back, etc.):
    special_first = group_code in ("C", "D", "E", "K")

    sorted_turns = sorted(user_turns.items())
    for i, (turn_num, message) in enumerate(sorted_turns):
        turn_counter += 1
        is_first = (i == 0)
        is_last = (i == len(sorted_turns) - 1)

        # Expected behavior for this turn
        expected = ""
        next_turn = turn_num + 1
        for t_num, t_text in expected_per_turn.items():
            if t_num == next_turn or (is_last and t_num >= turn_num):
                expected = t_text
                break
        if not expected:
            expected = case.get("expected_output", "")[:200]

        turn_obj = {
            "turn": turn_counter,
            "message": message,
            "is_setup": False,
            "expected_behavior": expected,
            "checks": {},
            "judge_criteria": [],
        }

        # ─── Distribute checks ───
        if len(sorted_turns) == 1:
            # Single user turn: everything goes here
            turn_obj["checks"] = rule_checks
            turn_obj["judge_criteria"] = judge_criteria

        elif is_first and not is_last:
            # First of multiple turns
            turn_obj["checks"].update(defensive_checks)

            if chart_on_first:
                turn_obj["checks"].update(chart_output_checks)
            elif special_first:
                turn_obj["checks"].update(exit_checks)
                turn_obj["checks"].update(other_checks)
            else:
                # Missing Info / other: first turn should trigger ask-back
                turn_obj["checks"].update(ask_info_checks)

            if not turn_obj["checks"]:
                turn_obj["checks"]["not_empty"] = {"type": "not_empty"}

        elif is_last:
            # Last turn
            turn_obj["checks"].update(defensive_checks)

            if chart_on_last:
                turn_obj["checks"].update(chart_output_checks)
            elif chart_on_first:
                # Last turn is follow-up, just basic checks
                turn_obj["checks"].update(exit_checks)
                turn_obj["checks"].update(other_checks)
            else:
                turn_obj["checks"].update(other_checks)
                turn_obj["checks"].update(exit_checks)
                turn_obj["checks"].update(chart_output_checks)

            # Judge criteria always on last turn (evaluates full conversation)
            turn_obj["judge_criteria"] = judge_criteria

            if not turn_obj["checks"]:
                turn_obj["checks"]["not_empty"] = {"type": "not_empty"}

        else:
            # Middle turns
            turn_obj["checks"] = {"not_empty": {"type": "not_empty"}}
            turn_obj["checks"].update(defensive_checks)

        turns.append(turn_obj)

    return {
        "id": case["id"],
        "name": case["name"],
        "group": group_code,
        "group_name": case["group"],
        "domain": domain,
        "priority": case.get("priority", "Medium"),
        "description": case.get("notes", ""),
        "preconditions": case["preconditions"],
        "original_pass_fail_criteria": case["pass_fail_criteria"],
        "turns": turns,
    }


def main():
    # Đảm bảo stdout dùng UTF-8 (cần thiết trên Windows terminal)
    sys.stdout.reconfigure(encoding="utf-8")

    # Resolve paths relative to this file's directory (tests/)
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(tests_dir, "test_cases.json")
    default_output = os.path.join(tests_dir, "test_cases_for_runner.json")

    input_path = sys.argv[1] if len(sys.argv) > 1 else default_input
    output_path = sys.argv[2] if len(sys.argv) > 2 else default_output

    with open(input_path, "r", encoding="utf-8") as f:
        raw_cases = json.load(f)

    print(f"Converting {len(raw_cases)} test cases...")

    converted = []
    errors = []

    for case in raw_cases:
        try:
            result = convert_case(case)
            converted.append(result)
            turns_count = len(result["turns"])
            checks_count = sum(len(t["checks"]) for t in result["turns"])
            judge_count = sum(len(t["judge_criteria"]) for t in result["turns"])
            print(f"  ✓ {result['id']:12} | {result['group']}-{result['group_name']:20} | "
                  f"turns={turns_count} | checks={checks_count} | judge_criteria={judge_count}")
        except Exception as e:
            errors.append({"id": case["id"], "error": str(e)})
            print(f"  ✗ {case['id']:12} | ERROR: {e}")

    # Wrap in expected format
    output = {
        "metadata": {
            "version": "2.0",
            "total_cases": len(converted),
            "groups": {v: k for k, v in GROUP_MAP.items()},
            "check_types": [
                "not_empty", "contains", "not_contains",
                "contains_any", "not_contains_any", "count_min", "only_columns"
            ],
            "judge_enabled": True,
            "description": "Auto-converted from test_cases.json with rule-based checks + LLM-as-Judge criteria",
        },
        "test_cases": converted,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"CONVERSION COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Total:     {len(raw_cases)}")
    print(f"  Converted: {len(converted)}")
    print(f"  Errors:    {len(errors)}")
    print(f"  Output:    {output_path}")

    if errors:
        print(f"\n  ERRORS:")
        for e in errors:
            print(f"    {e['id']}: {e['error']}")

    # Stats
    total_checks = sum(
        sum(len(t["checks"]) for t in c["turns"])
        for c in converted
    )
    total_judge = sum(
        sum(len(t["judge_criteria"]) for t in c["turns"])
        for c in converted
    )
    total_turns = sum(len(c["turns"]) for c in converted)
    setup_turns = sum(
        sum(1 for t in c["turns"] if t.get("is_setup"))
        for c in converted
    )

    print(f"\n  STATS:")
    print(f"    Total turns:       {total_turns} ({setup_turns} setup turns)")
    print(f"    Rule-based checks: {total_checks}")
    print(f"    Judge criteria:    {total_judge}")
    print(f"    Avg checks/case:   {total_checks / max(len(converted), 1):.1f}")
    print(f"    Avg judge/case:    {total_judge / max(len(converted), 1):.1f}")


if __name__ == "__main__":
    main()
