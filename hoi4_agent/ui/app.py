"""
HOI4 Universal Modding Agent v4.
Streamlit entry point.
"""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from hoi4_agent.config.settings import Config
from hoi4_agent.core.chat_session import ChatSessionManager
from hoi4_agent.core.scanner import ModScanner, ModContext, find_mod_root
from hoi4_agent.ui.sidebar import render_sidebar
from hoi4_agent.ui.chat_view import render_chat


def _resolve_mod_root() -> Path:
    env = os.environ.get("MOD_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    cwd = Path.cwd()
    found = find_mod_root(cwd)
    return found or cwd


def main():
    load_dotenv()

    st.set_page_config(
        page_title="HOI4 Modding Agent",
        page_icon="🎮",
        layout="centered",
    )

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    if "mod_context" not in st.session_state:
        mod_root = _resolve_mod_root()
        with st.spinner(f"🔍 모드 스캔 중... ({mod_root.name})"):
            st.session_state.mod_context = ModScanner().scan(mod_root)
            st.session_state.mod_root = mod_root

    ctx: ModContext = st.session_state.mod_context
    mod_root: Path = st.session_state.mod_root

    if "chat_manager" not in st.session_state:
        st.session_state.chat_manager = ChatSessionManager(
            mod_root / ".chat_sessions.db"
        )

    if "mcp_manager" not in st.session_state:
        from hoi4_agent.core.mcp_client import MCPManager
        mcp_cfg = mod_root / "mcp_servers.json"
        if not mcp_cfg.exists():
            mcp_cfg = Path(__file__).resolve().parents[2] / "mcp_servers.json"
        st.session_state.mcp_manager = MCPManager.from_config_file(mcp_cfg)

    if "current_session_id" not in st.session_state:
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

    config = Config(
        anthropic_key=anthropic_key,
        gemini_key=gemini_key or None,
        mod_root=mod_root,
    )

    st.title(f"🎮 {ctx.mod_name or 'HOI4'} Modding Agent")
    mcp_mgr = st.session_state.get("mcp_manager")
    mcp_count = len(mcp_mgr.discover_tools()) if mcp_mgr and mcp_mgr.available else 0
    tool_total = 16 + mcp_count
    st.caption(
        f"v4 · {len(ctx.countries)}개 국가 · "
        f"{len(ctx.characters)}개 캐릭터 · {tool_total}개 도구 · 영구 세션"
    )

    if not anthropic_key:
        anthropic_key = st.text_input("Anthropic API Key:", type="password")
        if not anthropic_key:
            st.warning("ANTHROPIC_API_KEY 를 설정하세요.")
            st.stop()
        config = Config(
            anthropic_key=anthropic_key,
            gemini_key=gemini_key or None,
            mod_root=mod_root,
        )

    if not gemini_key:
        gemini_key = st.text_input(
            "Gemini API Key (포트레잇용, 선택):", type="password"
        )
        if gemini_key:
            config = Config(
                anthropic_key=config.anthropic_key,
                gemini_key=gemini_key,
                mod_root=mod_root,
            )

    render_sidebar(ctx, mod_root, config.gemini_key or "")
    render_chat(ctx, mod_root, config)


if __name__ == "__main__":
    main()
