"""Sidebar UI components: session management and mod info."""
import os

import streamlit as st

from hoi4_agent.core.scanner import ModContext, ModScanner


def render_sidebar(ctx: ModContext, mod_root, gemini_key: str, config):
    with st.sidebar:
        _render_session_panel()
        st.divider()
        _render_session_search()
        st.divider()
        _render_model_settings(config)
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


def _render_session_search():
    query = st.text_input("🔍 세션 검색", placeholder="키워드 입력...")
    if query:
        results = st.session_state.chat_manager.search_messages(query, limit=10)
        if results:
            st.caption(f"{len(results)}건 발견")
            for r in results:
                with st.expander(f"[{r['role']}] {r['title']}", expanded=False):
                    st.text(r["content"][:300])
                    if st.button("이 세션으로 이동", key=f"jump_{r['session_id']}_{r['timestamp']}"):
                        st.session_state.current_session_id = r["session_id"]
                        st.session_state.messages = (
                            st.session_state.chat_manager.load_messages(r["session_id"])
                        )
                        st.rerun()
        else:
            st.caption("결과 없음")


def _render_model_settings(config):
    st.header("⚙️ AI 모델 설정")
    
    if config.ai_provider == "ollama":
        st.success(f"🦙 **Ollama** · `{config.ollama_model}` · 무료")
        st.caption(f"서버: {config.ollama_base_url}")
    elif config.ai_provider == "gemini":
        st.success(f"💎 **Gemini** · `{config.gemini_model}`")
        st.caption("💰 Flash: $0.50/1M input · $3.00/1M output")
    elif config.ai_provider == "openai":
        st.success(f"🧠 **GPT** · `{config.openai_model}`")
        st.caption("💰 가격은 모델에 따라 다름")
    elif config.ai_provider == "anthropic":
        st.warning(f"🤖 **Claude** · `{config.default_model}` · 유료")
        model_options = {
            "자동 (Sonnet 기본) - 권장": "auto",
            "절약 모드 (Haiku) - 빠르고 저렴": "haiku", 
            "표준 모드 (Sonnet) - 균형": "sonnet",
            "고급 모드 (Opus) - 복잡한 작업": "opus"
        }
        
        selected = st.selectbox(
            "모델 선택",
            options=list(model_options.keys()),
            index=0,
            help="간단한 작업은 Haiku, 중간 작업은 Sonnet, 어려운 작업은 Opus를 사용합니다.",
            key="model_selection"
        )
        
        model_mode = model_options[selected]
        
        if model_mode == "haiku":
            st.caption("💰 비용: 매우 저렴 (Opus의 1/18)")
        elif model_mode == "sonnet":
            st.caption("💰 비용: 표준 (Opus의 1/5)")
        elif model_mode == "opus":
            st.caption("💰 비용: 고가 (5배)")
        else:
            st.caption("💰 자동: 작업에 따라 Haiku/Sonnet/Opus 선택")


def _render_mod_info(ctx: ModContext, mod_root):
    st.header("📊 모드 정보")
    for k, v in ctx.to_stats_dict().items():
        st.markdown(f"**{k}**: {v}")


def _render_tool_status(gemini_key: str):
    tavily_ok = bool(os.environ.get("TAVILY_API_KEY"))
    st.markdown(f"🔍 Tavily: {'✅' if tavily_ok else '⚠️ DDGS 폴백'}")
    st.markdown("📖 Wikipedia: ✅")
    st.markdown(f"🖼️ Gemini: {'✅' if gemini_key else '❌'}")

    mcp = st.session_state.get("mcp_manager")
    if mcp and mcp.available:
        tools = mcp.discover_tools()
        st.markdown(f"🔌 MCP: ✅ ({len(tools)}개 도구)")
    elif mcp and mcp.configs:
        st.markdown("🔌 MCP: ⚠️ `pip install mcp` 필요")
    else:
        st.markdown("🔌 MCP: — (mcp_servers.json 없음)")


def _render_rescan(mod_root):
    if st.button("🔄 모드 재스캔"):
        with st.spinner("스캔 중..."):
            st.session_state.mod_context = ModScanner().scan(mod_root)
        st.rerun()
