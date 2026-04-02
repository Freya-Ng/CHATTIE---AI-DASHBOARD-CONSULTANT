import streamlit as st
from config.settings import DEFAULT_PROVIDER


def init_state():
    defaults = {
        "messages": [],
        "provider": DEFAULT_PROVIDER,
        "api_key": "",
        "api_key_valid": False,
        "language": "vi",
        "turn_count": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def add_message(role, content):
    st.session_state.messages.append({"role": role, "content": content})
    if role == "user":
        st.session_state.turn_count += 1


def get_messages():
    return st.session_state.messages


def clear_messages():
    st.session_state.messages = []
    st.session_state.turn_count = 0


def get_provider():
    return st.session_state.provider


def set_provider(p):
    st.session_state.provider = p


def get_api_key():
    return st.session_state.api_key


def set_api_key(k):
    st.session_state.api_key = k
    st.session_state.api_key_valid = bool(k and len(k) > 10)


def is_api_key_valid():
    return st.session_state.api_key_valid


def get_language():
    return st.session_state.language


def set_language(lang):
    st.session_state.language = lang


def get_turn_count():
    return st.session_state.turn_count


def build_conversation_context():
    msgs = get_messages()
    if len(msgs) <= 1:
        return msgs[-1]["content"] if msgs else ""
    parts = []
    for m in msgs[:-1]:
        tag = "[User trước đó]" if m["role"] == "user" else "[AI trước đó]"
        parts.append(f"{tag}: {m['content']}")
    parts.append(f"[User hiện tại]: {msgs[-1]['content']}")
    return "\n\n".join(parts)
