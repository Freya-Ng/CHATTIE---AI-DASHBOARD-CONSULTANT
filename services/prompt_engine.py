from config.settings import SYSTEM_PROMPT_PATHS


def load_system_prompt(provider="openai"):
    path = SYSTEM_PROMPT_PATHS.get(provider, SYSTEM_PROMPT_PATHS["openai"])
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_user_message(objective, num_charts, columns_info, audience="", bi_tool=""):
    cols_text = ""
    for i, col in enumerate(columns_info, 1):
        cols_text += f"  {i}. Tên cột: {col['name']} | Kiểu: {col['dtype']} | Ý nghĩa: {col['meaning']}\n"

    msg = f"""Mục tiêu Dashboard: {objective}
Số biểu đồ mong muốn: {num_charts}

Danh sách cột dữ liệu:
{cols_text}"""

    if audience:
        msg += f"\nĐối tượng xem Dashboard: {audience}"
    if bi_tool:
        msg += f"\nCông cụ BI đang sử dụng: {bi_tool}"

    return msg.strip()
