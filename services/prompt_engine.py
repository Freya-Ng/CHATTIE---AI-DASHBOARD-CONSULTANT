"""
Prompt Engine — Ghép system prompt cố định + thông tin user → final prompt.
"""

from config.settings import SYSTEM_PROMPT_PATHS


def load_system_prompt(provider: str = "openai") -> str:
    """Đọc system prompt theo provider (openai hoặc gemini)."""
    path = SYSTEM_PROMPT_PATHS.get(provider, SYSTEM_PROMPT_PATHS["openai"])
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_user_message(
    objective: str,
    num_charts: int,
    columns_info: list[dict],
    audience: str = "",
    bi_tool: str = "",
) -> str:
    """
    Tạo user message từ metadata người dùng nhập.

    Args:
        objective:    Mục tiêu dashboard (VD: "Phân tích doanh thu Q3")
        num_charts:   Số biểu đồ mong muốn
        columns_info: List of dict, mỗi dict gồm:
                      {"name": "revenue", "dtype": "float", "meaning": "Doanh thu đơn hàng"}
        audience:     Đối tượng xem dashboard (VD: "CEO", "Team Lead")
        bi_tool:      Công cụ BI đang dùng (VD: "Power BI", "Tableau")

    Returns:
        Chuỗi user message đã format sẵn.
    """

    # Format bảng cột cho dễ đọc
    columns_text = ""
    for i, col in enumerate(columns_info, 1):
        columns_text += (
            f"  {i}. Tên cột: {col['name']} | "
            f"Kiểu dữ liệu: {col['dtype']} | "
            f"Ý nghĩa: {col['meaning']}\n"
        )

    # Ghép thành message hoàn chỉnh
    message = f"""
══════════════════════════════════════
THÔNG TIN TỪ NGƯỜI DÙNG
══════════════════════════════════════
Mục tiêu Dashboard: {objective}
Số biểu đồ mong muốn: {num_charts}

Danh sách cột dữ liệu:
{columns_text}"""

    # Thêm thông tin tùy chọn (nếu có)
    if audience:
        message += f"\nĐối tượng xem Dashboard: {audience}"
    if bi_tool:
        message += f"\nCông cụ BI đang sử dụng: {bi_tool}"

    return message.strip()
