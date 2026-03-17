"""Sidebar UI components: session management and mod info."""
import os

import streamlit as st

from hoi4_agent.core.scanner import ModContext, ModScanner


def render_sidebar(ctx: ModContext, mod_root, gemini_key: str):
    with st.sidebar:
        _render_session_panel()
        st.divider()
        _render_mod_info(ctx, mod_root)
        st.divider()
        _render_tool_status(gemini_key)
        st.divider()
        _render_rescan(mod_root)


def _render_session_panel():
    st.header("💬 대화 세션")

    sessions = st.session_state.chat_manager.list_sessions()
    if sessions:
        session_options = {
            f"{s['title']} ({s['message_count']}개 메시지)": s["session_id"]
            for s in sessions
        }
        current_title = next(
            (
                k
                for k, v in session_options.items()
                if v == st.session_state.current_session_id
            ),
            list(session_options.keys())[0] if session_options else None,
        )
        selected = st.selectbox(
            "세션 선택",
            options=list(session_options.keys()),
            index=(
                list(session_options.keys()).index(current_title)
                if current_title
                else 0
            ),
        )

        if session_options[selected] != st.session_state.current_session_id:
            st.session_state.current_session_id = session_options[selected]
            st.session_state.messages = (
                st.session_state.chat_manager.load_messages(
                    st.session_state.current_session_id
                )
            )
            st.rerun()

    col1, col2, col3 = st.columns(3)
    if col1.button("➕ 새 대화"):
        st.session_state.current_session_id = (
            st.session_state.chat_manager.create_session()
        )
        st.session_state.messages = []
        st.rerun()

    if col2.button("🗑️ 삭제"):
        if len(sessions) > 1:
            st.session_state.chat_manager.delete_session(
                st.session_state.current_session_id
            )
            latest = st.session_state.chat_manager.get_latest_session()
            if latest:
                st.session_state.current_session_id = latest
                st.session_state.messages = (
                    st.session_state.chat_manager.load_messages(latest)
                )
            else:
                st.session_state.current_session_id = (
                    st.session_state.chat_manager.create_session()
                )
                st.session_state.messages = []
            st.rerun()
        else:
            st.warning("마지막 세션은 삭제할 수 없습니다.")

    if col3.button("🔄 새로고침"):
        st.session_state.messages = (
            st.session_state.chat_manager.load_messages(
                st.session_state.current_session_id
            )
        )
        st.rerun()


def _render_mod_info(ctx: ModContext, mod_root):
    st.header("📊 모드 정보")
    for k, v in ctx.to_stats_dict().items():
        st.markdown(f"**{k}**: {v}")


def _render_tool_status(gemini_key: str):
    tavily_ok = bool(os.environ.get("TAVILY_API_KEY"))
    st.markdown(f"🔍 Tavily: {'✅' if tavily_ok else '⚠️ DDGS 폴백'}")
    st.markdown("📖 Wikipedia: ✅")
    st.markdown(f"🖼️ Gemini: {'✅' if gemini_key else '❌'}")


def _render_rescan(mod_root):
    if st.button("🔄 모드 재스캔"):
        with st.spinner("스캔 중..."):
            st.session_state.mod_context = ModScanner().scan(mod_root)
        st.rerun()
