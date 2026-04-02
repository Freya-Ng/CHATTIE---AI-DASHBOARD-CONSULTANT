import streamlit as st
from utils.state_manager import get_language

EXAMPLES = {
    "vi": [
        ("📈 Doanh thu bán hàng",
         "Tôi cần 4 biểu đồ phân tích doanh thu bán hàng theo quý.\n\nCột dữ liệu:\n1. order_date (datetime) — Ngày đặt hàng\n2. revenue (float) — Doanh thu\n3. cost (float) — Giá vốn\n4. product_category (string) — Danh mục sản phẩm\n5. region (string) — Khu vực (Bắc/Trung/Nam)\n\nNgười xem: Trưởng phòng kinh doanh\n\nCông cụ: Power BI"),
        ("📋 Khảo sát khách hàng",
         "Tôi cần 3 biểu đồ phân tích khảo sát khách hàng.\n\nCột dữ liệu:\n1. age_group (string) — Nhóm tuổi\n2. satisfaction_score (float) — Điểm hài lòng (1-10)\n3. recommend_score (integer) — Điểm NPS (0-10)\n4. feedback_category (string) — Loại phản hồi\n\nNgười xem: Trưởng phòng CSKH\n\nông cụ: Google Data Studio"),
        ("👥 Phân tích nhân sự",
         "Tôi cần 4 biểu đồ phân tích nghỉ việc và hiệu suất.\n\nCột dữ liệu:\n1. department (string) — Phòng ban\n2. hire_date (datetime) — Ngày vào làm\n3. salary (float) — Lương tháng\n4. performance_score (float) — Điểm hiệu suất (1-5)\n5. is_resigned (boolean) — Đã nghỉ việc\n\nNgười xem: Giám đốc nhân sự\n\nCông cụ: Tableau"),
    ],
    "en": [
        ("📈 Sales revenue",
         "I need 4 charts for quarterly sales revenue analysis.\n\nColumns:\n1. order_date (datetime) — Order date\n2. revenue (float) — Revenue\n3. cost (float) — Cost\n4. product_category (string) — Category\n5. region (string) — Region\n\nAudience: Sales Manager\nBI tool: Power BI"),
        ("📋 Customer survey",
         "I need 3 charts for customer satisfaction analysis.\n\nColumns:\n1. age_group (string) — Age group\n2. satisfaction_score (float) — Score (1-10)\n3. recommend_score (integer) — NPS (0-10)\n4. feedback_category (string) — Type\n\nAudience: CS Manager\nBI tool: Google Data Studio"),
        ("👥 HR analytics",
         "I need 4 charts for employee turnover analysis.\n\nColumns:\n1. department (string) — Department\n2. hire_date (datetime) — Hire date\n3. salary (float) — Salary\n4. performance_score (float) — Score (1-5)\n5. is_resigned (boolean) — Resigned\n\nAudience: HR Director\nBI tool: Tableau"),
    ],
}


def render_welcome():
    lang = get_language()

    st.markdown("")
    st.markdown("")

    # Hero
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        if lang == "vi":
            st.markdown("### Xin chào! Tôi là chuyên gia tư vấn Dashboard.")
            st.caption("Mô tả data của bạn, tôi sẽ gợi ý biểu đồ phù hợp nhất.")
        else:
            st.markdown("### Hello! I'm your Dashboard Consultant.")
            st.caption("Describe your data, I'll suggest the best charts.")

    st.markdown("")

    # 4 info cards
    items_vi = [
        ("🎯", "Mục tiêu phân tích", "VD: doanh thu theo quý"),
        ("📊", "Danh sách cột", "Tên, kiểu dữ liệu, ý nghĩa"),
        ("👤", "Đối tượng xem", "CEO, Trưởng phòng, Analyst"),
        ("🛠️", "Công cụ BI", "Power BI, Tableau, Looker"),
    ]
    items_en = [
        ("🎯", "Analysis goal", "e.g., quarterly revenue"),
        ("📊", "Data columns", "Name, type, meaning"),
        ("👤", "Audience", "CEO, Manager, Analyst"),
        ("🛠️", "BI tool", "Power BI, Tableau, Looker"),
    ]
    items = items_vi if lang == "vi" else items_en

    cols = st.columns(4)
    for i, (icon, title, desc) in enumerate(items):
        with cols[i]:
            st.metric(label=f"{icon} {title}", value="", delta=desc)

    st.markdown("")
    st.divider()

    # Example buttons
    if lang == "vi":
        st.caption("⚡ Hoặc thử ngay với ví dụ mẫu:")
    else:
        st.caption("⚡ Or try a quick example:")

    examples = EXAMPLES[lang]
    ex_cols = st.columns(len(examples))
    for i, (label, prompt) in enumerate(examples):
        with ex_cols[i]:
            if st.button(label, key=f"example_{i}", use_container_width=True):
                return prompt

    return None
