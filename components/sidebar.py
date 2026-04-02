import streamlit as st
from utils.state_manager import (
    get_provider, set_provider, get_api_key, set_api_key,
    get_language, set_language, clear_messages, get_turn_count,
    is_api_key_valid,
)
from config.settings import SUPPORTED_PROVIDERS

T = {
    "vi": dict(
        provider="🤖 Nhà cung cấp AI", api_key="🔑 API Key",
        api_ph="Nhập API key tại đây...",
        api_help="🔒 Key chỉ lưu trong phiên này, không bao giờ lưu trữ vĩnh viễn.",
        lang="🌐 Ngôn ngữ", new_chat="✨ Hội thoại mới",
        session="📌 Phiên hiện tại", turns="lượt",
        ready="Sẵn sàng", no_key="Chưa có API key",
    ),
    "en": dict(
        provider="🤖 AI Provider", api_key="🔑 API Key",
        api_ph="Enter your API key...",
        api_help="🔒 Key is stored only in this session, never persisted.",
        lang="🌐 Language", new_chat="✨ New conversation",
        session="📌 Current session", turns="turns",
        ready="Ready", no_key="No API key",
    ),
}


def render_sidebar():
    lang = get_language()
    t = T[lang]

    with st.sidebar:
        # Logo
        st.image("assets/logo.jpg", use_container_width=True)
        st.caption("AI-powered chart advisor" if lang == "en" else "Tư vấn biểu đồ bằng AI")
        st.divider()

        # Provider
        st.markdown(f"**{t['provider']}**")
        providers = list(SUPPORTED_PROVIDERS.keys())
        idx = providers.index(get_provider()) if get_provider() in providers else 0
        sel = st.radio(
            "provider_radio", providers,
            format_func=lambda x: SUPPORTED_PROVIDERS[x]["display_name"],
            index=idx, horizontal=True, label_visibility="collapsed",
        )
        if sel != get_provider():
            set_provider(sel)
            st.rerun()

        model = SUPPORTED_PROVIDERS[get_provider()]["model"]
        st.caption(f"Model: `{model}`")
        st.divider()

        # API Key
        st.markdown(f"**{t['api_key']}**")
        key = st.text_input(
            "api_input", value=get_api_key(), type="password",
            placeholder=t["api_ph"], label_visibility="collapsed",
        )
        if key != get_api_key():
            set_api_key(key)

        if is_api_key_valid():
            st.success(f"✅ {t['ready']}")
        else:
            st.warning(f"⚠️ {t['no_key']}")

        st.caption(t["api_help"])
        st.divider()

        # Language
        st.markdown(f"**{t['lang']}**")
        lang_sel = st.radio(
            "lang_radio", ["vi", "en"],
            format_func=lambda x: "🇻🇳 Tiếng Việt" if x == "vi" else "🇺🇸 English",
            index=["vi", "en"].index(lang), horizontal=True,
            label_visibility="collapsed",
        )
        if lang_sel != lang:
            set_language(lang_sel)
            st.rerun()

        st.divider()

        # New chat
        if st.button(t["new_chat"], use_container_width=True, type="primary"):
            clear_messages()
            st.rerun()

        # Session info
        turns = get_turn_count()
        if turns > 0:
            st.info(f"{t['session']}: {turns} {t['turns']} · {model}")
