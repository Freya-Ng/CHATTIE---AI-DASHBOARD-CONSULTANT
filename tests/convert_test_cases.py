"""
═══════════════════════════════════════════════════════════════
CONVERTER V2: Chuyển test cases sang format tương thích test_runner.py
═══════════════════════════════════════════════════════════════

V2 Changes:
  - Parse "Turn N:" prefix trong pass_fail_criteria
  - Gán checks vào đúng turn thay vì heuristic theo group
  - "Both:" prefix → gán vào tất cả turns
  - Criteria không có prefix → fallback heuristic cũ (backward compatible)

Input:  test_cases.json (format hiện tại)
Output: test_cases_for_runner.json
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

DOMAIN_KEYWORDS = {
    "doanh thu": "Sales", "kinh doanh": "Sales",
    "marketing": "Marketing", "quảng cáo": "Marketing",
    "nhân sự": "HR", "nghỉ việc": "HR",
    "y tế": "Healthcare", "lâm sàng": "Healthcare",
    "khảo sát": "Survey", "hài lòng": "Survey",
    "tài chính": "Finance", "giáo dục": "Education",
    "logistics": "Logistics", "vận chuyển": "Logistics",
    "thương mại điện tử": "E-commerce", "ecommerce": "E-commerce",
    "IoT": "IoT", "cảm biến": "IoT", "nhiệt độ": "IoT",
    "game": "Gaming", "sản xuất": "Manufacturing",
}

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
    """Parse specific_input thành dict {turn_number: message}."""
    turns = {}
    pattern = r"Turn\s+(\d+)\s*:"
    matches = list(re.finditer(pattern, text))

    for i, match in enumerate(matches):
        turn_num = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw_msg = text[start:end].strip()
        raw_msg = re.sub(r'\s*\|\s*$', '', raw_msg)
        raw_msg = raw_msg.strip()
        if (raw_msg.startswith("'") and raw_msg.endswith("'")) or \
           (raw_msg.startswith('"') and raw_msg.endswith('"')):
            raw_msg = raw_msg[1:-1]
        turns[turn_num] = raw_msg.strip()

    return turns


# ─────────────────────────────────────────────
# TURN PREFIX PARSER
# ─────────────────────────────────────────────

def parse_turn_prefix(criterion: str) -> tuple:
    """
    Parse "Turn N: ..." hoặc "Both: ..." prefix.
    Returns: (turn_target, clean_criterion)
      turn_target: int (specific turn), "all" (Both:), None (no prefix)
      clean_criterion: criterion text without prefix
    """
    # Match "Turn 1:", "Turn 2:", etc.
    m = re.match(r'^Turn\s+(\d+)\s*:\s*(.+)$', criterion, re.IGNORECASE)
    if m:
        return int(m.group(1)), m.group(2).strip()

    # Match "Both:"
    m = re.match(r'^Both\s*:\s*(.+)$', criterion, re.IGNORECASE)
    if m:
        return "all", m.group(1).strip()

    # No prefix
    return None, criterion


# ─────────────────────────────────────────────
# SINGLE CRITERION → CHECK
# ─────────────────────────────────────────────

def criterion_to_check(criterion: str, index: int) -> tuple:
    """
    Convert 1 criterion thành (check_name, check_config) hoặc None.
    Returns: (check_name, check_config, is_also_judge)
      - (name, config, False): rule-based only
      - (name, config, True): rule-based + also send to judge
      - (None, None, True): judge-only (no rule check possible)
    """
    crit_lower = criterion.lower()

    # ═══ Không sinh code ═══
    if "không sinh code" in crit_lower or "không viết code" in crit_lower:
        return "no_code", {
            "type": "not_contains_any",
            "values": ["```python", "```r", "```sql", "```js",
                       "import ", "def ", "SELECT ", "CREATE TABLE"],
            "criteria_text": criterion,
        }, False

    # ═══ Đếm số chart ═══
    if "đúng" in crit_lower and "chart" in crit_lower:
        match = re.search(r'(\d+)\s*chart', crit_lower)
        if match:
            return "chart_count", {
                "type": "count_min",
                "substring": "Chart",
                "min": int(match.group(1)),
                "criteria_text": criterion,
            }, False

    # ═══ Format chuẩn ═══
    if "tổng tôi gợi ý" in crit_lower or "format output đúng chuẩn" in crit_lower:
        return "format_standard", {
            "type": "contains_any",
            "values": ["tổng tôi gợi ý", "Tổng tôi gợi ý", "gợi ý", "chart"],
            "criteria_text": criterion,
        }, False

    # ═══ Câu hỏi xác nhận / mời phản hồi ═══
    if any(kw in crit_lower for kw in ["câu hỏi xác nhận", "hỏi xác nhận",
                                        "chỉnh sửa gì không", "câu hỏi mở cho chỉnh sửa",
                                        "câu mời phản hồi", "kết thúc bằng câu"]):
        return "has_confirmation_q", {
            "type": "contains_any",
            "values": ["chỉnh sửa", "điều chỉnh", "thay đổi", "ý kiến",
                       "phản hồi", "hài lòng"],
            "criteria_text": criterion,
        }, False

    # ═══ Feature engineering ═══
    if "feature engineering" in crit_lower or ("có" in crit_lower and "công thức" in crit_lower):
        return "has_feature_eng", {
            "type": "contains_any",
            "values": ["công thức", "Công thức", "feature engineering",
                       "tính toán", "= "],
            "criteria_text": criterion,
        }, True  # Also judge

    # ═══ Đủ thành phần mỗi chart ═══
    if "đủ" in crit_lower and ("thành phần" in crit_lower or "mục đích" in crit_lower):
        return "chart_components", {
            "type": "contains_any",
            "values": ["Dạng chart", "dạng chart", "Chart type", "Loại biểu đồ",
                       "Bar", "Line", "Pie", "Scatter", "Heatmap", "Table",
                       "Stacked", "Grouped", "Treemap", "Funnel", "Donut", "Area",
                       "Waterfall", "KPI Card", "Gauge", "Box Plot", "Histogram"],
            "criteria_text": criterion,
        }, False

    # ═══ Bot từ chối / giới hạn ═══
    if ("bot từ chối" in crit_lower or "bot nêu rõ" in crit_lower) and \
       ("chart" in crit_lower or "giới hạn" in crit_lower):
        return "reject_overcapacity", {
            "type": "contains_any",
            "values": ["tối đa", "giới hạn", "không thể", "6 chart",
                       "quá nhiều", "giảm", "đề xuất"],
            "criteria_text": criterion,
        }, False

    # ═══ Bot gợi ý chart NGAY (must check BEFORE hỏi lại/hỏi thêm) ═══
    if "gợi ý chart ngay" in crit_lower or "output chart ngay" in crit_lower:
        return None, None, True

    # ═══ KHÔNG cần output chart ═══
    if "không cần output chart" in crit_lower or "không kỳ vọng chart" in crit_lower \
       or "không cần chart mới" in crit_lower:
        return None, None, True

    # ═══ Bot hỏi lại thông tin ═══
    if any(kw in crit_lower for kw in ["hỏi lại", "hỏi thêm", "hỏi bổ sung",
                                        "hỏi thông tin"]):
        return f"asks_for_info_{index}", {
            "type": "contains_any",
            "values": ["?", "cho tôi biết", "cung cấp", "bạn có thể",
                       "thông tin", "cho mình biết", "vui lòng",
                       "hãy cung cấp", "bổ sung"],
            "criteria_text": criterion,
        }, False

    # ═══ Giọng điệu chuyên nghiệp ═══
    if "không phản ứng tiêu cực" in crit_lower or "chuyên nghiệp" in crit_lower:
        return "professional_tone", {
            "type": "not_contains_any",
            "values": ["ngu", "mày", "thô lỗ", "khó chịu", "bực mình", "tức giận"],
            "criteria_text": criterion,
        }, True  # Also judge

    # ═══ Tạm biệt / dừng ═══
    if any(kw in crit_lower for kw in ["dừng lại", "tạm biệt", "chào tạm biệt"]):
        return f"graceful_exit_{index}", {
            "type": "contains_any",
            "values": ["tạm biệt", "chào", "cảm ơn", "hẹn gặp", "chúc",
                       "quay lại", "sẵn sàng", "hỗ trợ", "bye", "giúp đỡ"],
            "criteria_text": criterion,
        }, False

    # ═══ Default: judge-only ═══
    return None, None, True


# ─────────────────────────────────────────────
# CRITERIA → TURN-TAGGED CHECKS
# ─────────────────────────────────────────────

def criteria_to_checks_v2(criteria_list: list, case_id: str, num_user_turns: int) -> dict:
    """
    Chuyển pass_fail_criteria thành turn-tagged structure.

    Returns: {
        "by_turn": {
            1: {"checks": {...}, "judge": [...]},
            2: {"checks": {...}, "judge": [...]},
            ...
        },
        "all_turns": {"checks": {...}, "judge": [...]},
        "untagged": {"checks": {...}, "judge": [...]},
    }
    """
    result = {
        "by_turn": {},
        "all_turns": {"checks": {}, "judge": []},
        "untagged": {"checks": {}, "judge": []},
    }

    for i, criterion in enumerate(criteria_list):
        # Step 1: Parse turn prefix
        turn_target, clean_text = parse_turn_prefix(criterion)

        # Step 2: Convert to check
        check_name, check_config, is_judge_also = criterion_to_check(clean_text, i)

        # Step 3: Determine destination
        if turn_target == "all":
            dest = result["all_turns"]
        elif turn_target is not None:
            if turn_target not in result["by_turn"]:
                result["by_turn"][turn_target] = {"checks": {}, "judge": []}
            dest = result["by_turn"][turn_target]
        else:
            dest = result["untagged"]

        # Step 4: Add check and/or judge
        if check_name and check_config:
            dest["checks"][check_name] = check_config
        if is_judge_also or (not check_name):
            dest["judge"].append(criterion)  # Keep original text with prefix for context

    return result


# ─────────────────────────────────────────────
# DOMAIN INFERENCE
# ─────────────────────────────────────────────

def infer_domain(case: dict) -> str:
    text = f"{case.get('name', '')} {case.get('notes', '')} {case.get('specific_input', '')}".lower()
    for keyword, domain in DOMAIN_KEYWORDS.items():
        if keyword.lower() in text:
            return domain
    return "General"


# ─────────────────────────────────────────────
# BUILD SETUP TURN
# ─────────────────────────────────────────────

def get_setup_message(preconditions: str, case_id: str) -> str:
    prec_lower = preconditions.lower()
    if "4 chart" in prec_lower:
        return SETUP_HAPPY_PATH_4CHART
    elif "3 chart" in prec_lower:
        return SETUP_HAPPY_PATH_3CHART
    elif "happy path" in prec_lower or "đã hoàn thành" in prec_lower:
        return SETUP_HAPPY_PATH_4CHART
    return SETUP_GENERIC


# ─────────────────────────────────────────────
# MAIN CONVERTER
# ─────────────────────────────────────────────

def convert_case(case: dict) -> dict:
    group_code = GROUP_MAP.get(case.get("group", ""), "X")

    # Also try group_name if group didn't match
    if group_code == "X" and case.get("group_name"):
        group_code = GROUP_MAP.get(case["group_name"], "X")

    domain = case.get("domain") or infer_domain(case)
    user_turns = parse_specific_input(case["specific_input"])
    expected_per_turn = parse_specific_input(case.get("expected_output", ""))

    needs_setup = (
        "Đã" in case.get("preconditions", "") or
        "precondition" in case.get("preconditions", "").lower()
    )

    min_turn = min(user_turns.keys()) if user_turns else 1

    # ── Parse criteria with turn tags ──
    tagged_checks = criteria_to_checks_v2(
        case.get("pass_fail_criteria", []),
        case["id"],
        len(user_turns),
    )

    # ── Fallback heuristic for untagged checks ──
    # (same logic as v1, but only for criteria WITHOUT Turn prefix)
    chart_output_checks = {}
    defensive_checks = {}
    ask_info_checks = {}
    exit_checks = {}
    other_checks = {}

    for name, cfg in tagged_checks["untagged"]["checks"].items():
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

    untagged_judge = tagged_checks["untagged"]["judge"]

    # ── Build turns ──
    turns = []
    turn_counter = 0

    # Setup turn
    if needs_setup and min_turn > 1:
        turn_counter += 1
        turns.append({
            "turn": turn_counter,
            "message": get_setup_message(case.get("preconditions", ""), case["id"]),
            "is_setup": True,
            "expected_behavior": f"Precondition setup: {case.get('preconditions', '')}",
            "checks": {"setup_not_empty": {"type": "not_empty"}},
            "judge_criteria": [],
        })

    # Heuristic flags (only for UNTAGGED criteria)
    chart_on_first = group_code in ("A", "G", "I", "J")
    chart_on_last = group_code in ("B",)
    special_first = group_code in ("C", "D", "E", "K") 

    sorted_turns = sorted(user_turns.items())

    for i, (turn_num, message) in enumerate(sorted_turns):
        turn_counter += 1
        is_first = (i == 0)
        is_last = (i == len(sorted_turns) - 1)
        actual_turn_num = i + 1  # 1-indexed user turn number

        # Expected behavior
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

        # ══════════════════════════════════════════
        # PRIORITY 1: Turn-tagged checks (from "Turn N:" prefix)
        # These ALWAYS override heuristic
        # ══════════════════════════════════════════
        if actual_turn_num in tagged_checks["by_turn"]:
            tagged = tagged_checks["by_turn"][actual_turn_num]
            turn_obj["checks"].update(tagged["checks"])
            turn_obj["judge_criteria"].extend(tagged["judge"])

        # ══════════════════════════════════════════
        # PRIORITY 2: "Both:" checks (all turns)
        # ══════════════════════════════════════════
        turn_obj["checks"].update(tagged_checks["all_turns"]["checks"])
        # Judge criteria from "Both:" only on last turn to avoid duplication
        if is_last:
            turn_obj["judge_criteria"].extend(tagged_checks["all_turns"]["judge"])

        # ══════════════════════════════════════════
        # PRIORITY 3: Untagged checks (heuristic fallback)
        # Only apply if NO turn-tagged checks were found for this criteria type
        # ══════════════════════════════════════════
        has_tagged_for_this_turn = actual_turn_num in tagged_checks["by_turn"]

        if not has_tagged_for_this_turn:
            # Use v1 heuristic for untagged criteria
            if len(sorted_turns) == 1:
                turn_obj["checks"].update(tagged_checks["untagged"]["checks"])
                turn_obj["judge_criteria"].extend(untagged_judge)

            elif is_first and not is_last:
                turn_obj["checks"].update(defensive_checks)
                if chart_on_first:
                    turn_obj["checks"].update(chart_output_checks)
                elif special_first:
                    turn_obj["checks"].update(exit_checks)
                    turn_obj["checks"].update(other_checks)
                else:
                    turn_obj["checks"].update(ask_info_checks)

            elif is_last:
                turn_obj["checks"].update(defensive_checks)
                if chart_on_last:
                    turn_obj["checks"].update(chart_output_checks)
                elif chart_on_first:
                    turn_obj["checks"].update(exit_checks)
                    turn_obj["checks"].update(other_checks)
                else:
                    turn_obj["checks"].update(other_checks)
                    turn_obj["checks"].update(exit_checks)
                    turn_obj["checks"].update(chart_output_checks)

                turn_obj["judge_criteria"].extend(untagged_judge)

            else:
                turn_obj["checks"].update(defensive_checks)
        else:
            # Even with tagged checks, always add defensive checks
            for name, cfg in defensive_checks.items():
                if name not in turn_obj["checks"]:
                    turn_obj["checks"][name] = cfg

        # Ensure at least 1 check
        if not turn_obj["checks"]:
            turn_obj["checks"]["not_empty"] = {"type": "not_empty"}

        # ══════════════════════════════════════════
        # LAST TURN: Add remaining untagged judge criteria
        # (only if they weren't already added via tags)
        # ══════════════════════════════════════════
        if is_last and untagged_judge:
            existing_judge = set(turn_obj["judge_criteria"])
            for jc in untagged_judge:
                if jc not in existing_judge:
                    turn_obj["judge_criteria"].append(jc)

        turns.append(turn_obj)

    return {
        "id": case["id"],
        "name": case["name"],
        "group": group_code,
        "group_name": case.get("group_name", case.get("group", "")),
        "domain": domain,
        "priority": case.get("priority", "Medium"),
        "description": case.get("notes", case.get("description", "")),
        "preconditions": case.get("preconditions", ""),
        "original_pass_fail_criteria": case.get("pass_fail_criteria", []),
        "turns": turns,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(tests_dir, "test_cases.json")
    default_output = os.path.join(tests_dir, "test_cases_for_runner.json")

    input_path = sys.argv[1] if len(sys.argv) > 1 else default_input
    output_path = sys.argv[2] if len(sys.argv) > 2 else default_output

    with open(input_path, "r", encoding="utf-8") as f:
        raw_cases = json.load(f)

    print(f"Converting {len(raw_cases)} test cases (V2 — turn-tagged)...")

    converted = []
    errors = []
    tagged_count = 0
    untagged_count = 0

    for case in raw_cases:
        try:
            result = convert_case(case)
            converted.append(result)

            # Count tagged vs untagged criteria
            for crit in case.get("pass_fail_criteria", []):
                prefix, _ = parse_turn_prefix(crit)
                if prefix is not None:
                    tagged_count += 1
                else:
                    untagged_count += 1

            turns_count = len(result["turns"])
            checks_count = sum(len(t["checks"]) for t in result["turns"])
            judge_count = sum(len(t["judge_criteria"]) for t in result["turns"])
            print(f"  ✓ {result['id']:12} | {result['group']}-{result['group_name'][:18]:18} | "
                  f"turns={turns_count} checks={checks_count} judge={judge_count}")
        except Exception as e:
            errors.append({"id": case.get("id", "?"), "error": str(e)})
            print(f"  ✗ {case.get('id', '?'):12} | ERROR: {e}")
            
    output = {
        "metadata": {
            "version": "2.1-turn-tagged",
            "total_cases": len(converted),
            "groups": {v: k for k, v in GROUP_MAP.items()},
            "check_types": [
                "not_empty", "contains", "not_contains",
                "contains_any", "not_contains_any", "count_min", "only_columns"
            ],
            "judge_enabled": True,
            "description": "Auto-converted with turn-tagged criteria routing",
        },
        "test_cases": converted,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"CONVERSION COMPLETE (V2)")
    print(f"{'=' * 60}")
    print(f"  Total:     {len(raw_cases)}")
    print(f"  Converted: {len(converted)}")
    print(f"  Errors:    {len(errors)}")
    print(f"  Output:    {output_path}")

    if errors:
        print(f"\n  ERRORS:")
        for e in errors:
            print(f"    {e['id']}: {e['error']}")

    total_checks = sum(sum(len(t["checks"]) for t in c["turns"]) for c in converted)
    total_judge = sum(sum(len(t["judge_criteria"]) for t in c["turns"]) for c in converted)
    total_turns = sum(len(c["turns"]) for c in converted)
    setup_turns = sum(sum(1 for t in c["turns"] if t.get("is_setup")) for c in converted)

    # Check for any group "X"
    x_groups = [c["id"] for c in converted if c["group"] == "X"]

    print(f"\n  STATS:")
    print(f"    Total turns:        {total_turns} ({setup_turns} setup)")
    print(f"    Rule-based checks:  {total_checks}")
    print(f"    Judge criteria:     {total_judge}")
    print(f"    Tagged criteria:    {tagged_count} (with Turn N: / Both: prefix)")
    print(f"    Untagged criteria:  {untagged_count} (heuristic fallback)")
    print(f"    Group 'X' cases:    {x_groups if x_groups else 'NONE ✓'}")


if __name__ == "__main__":
    main()
