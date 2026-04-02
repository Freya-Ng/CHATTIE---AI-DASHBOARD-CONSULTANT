"""
AI Dashboard Consultant
Chạy: streamlit run app.py
"""
import streamlit as st

st.set_page_config(
    page_title="Dashboard Consultant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from utils.state_manager import init_state, get_messages
from components.sidebar import render_sidebar
from components.welcome_screen import render_welcome
from components.chat_window import render_chat_messages, render_chat_input, handle_user_input

# Minimal CSS — chỉ polish nhẹ, theme chính nằm trong .streamlit/config.toml
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');

    /* Font */
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif !important; }

    /* Ẩn menu mặc định */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Chat area max-width */
    .stChatMessage { max-width: 850px; margin-left: auto; margin-right: auto; }
    [data-testid="stChatInput"] { max-width: 850px; margin-left: auto; margin-right: auto; }

    /* Chat input border radius */
    [data-testid="stChatInput"] textarea {
        border-radius: 14px !important;
        font-size: 15px !important;
    }

    /* Button style */
    .stButton > button {
        border-radius: 10px !important;
        font-weight: 500 !important;
        transition: all 0.15s ease !important;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
    }

    /* Smooth scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-thumb { background: #ccc; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)


def main():
    init_state()
    render_sidebar()

    messages = get_messages()
    if not messages:
        selected = render_welcome()
        if selected:
            handle_user_input(selected)
            st.rerun()
    else:
        render_chat_messages()

    render_chat_input()


if __name__ == "__main__":
    main()
