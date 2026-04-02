import streamlit as st
import time
from utils.state_manager import (
    get_messages, add_message, get_provider,
    get_api_key, is_api_key_valid, get_language,
    build_conversation_context,
)
from services.prompt_engine import load_system_prompt
from services.llm_router import get_consultation, get_consultation_stream


T = {
    "vi": dict(
        ph="Nhập tin nhắn... (VD: Tôi cần 3 biểu đồ phân tích doanh thu)",
        thinking="Đang suy nghĩ...",
        no_key="⚠️ Vui lòng nhập API key ở sidebar trước khi chat.",
        error="❌ Lỗi: ",
    ),
    "en": dict(
        ph="Type a message... (e.g., I need 3 charts for revenue analysis)",
        thinking="Thinking...",
        no_key="⚠️ Please enter your API key in the sidebar first.",
        error="❌ Error: ",
    ),
}


def _fake_stream(text):
    """Giả lập streaming từ text có sẵn — hiệu ứng gõ từng từ."""
    for word in text.split(" "):
        yield word + " "
        time.sleep(0.02)


def render_chat_messages():
    for msg in get_messages():
        avatar = "🤖" if msg["role"] == "assistant" else "🧑‍💻"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])


def handle_user_input(user_input):
    lang = get_language()
    t = T[lang]

    if not is_api_key_valid():
        st.error(t["no_key"])
        return

    # Lưu tin nhắn user
    add_message("user", user_input)
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(user_input)

    # Gọi API
    with st.chat_message("assistant", avatar="🤖"):
        provider = get_provider()
        system_prompt = load_system_prompt(provider)
        context = build_conversation_context()

        try:
            # Thử streaming trước
            stream = get_consultation_stream(
                provider=provider,
                api_key=get_api_key(),
                system_prompt=system_prompt,
                user_message=context,
            )

            if stream is not None:
                full_response = st.write_stream(stream)
            else:
                # Fallback: gọi thường rồi giả lập stream
                with st.spinner(t["thinking"]):
                    text = get_consultation(
                        provider=provider,
                        api_key=get_api_key(),
                        system_prompt=system_prompt,
                        user_message=context,
                    )
                full_response = st.write_stream(_fake_stream(text))

            add_message("assistant", full_response)

        except Exception as e:
            st.error(f"{t['error']}{str(e)}")


def render_chat_input():
    lang = get_language()
    t = T[lang]

    user_input = st.chat_input(t["ph"])
    if user_input:
        handle_user_input(user_input)
        st.rerun()
