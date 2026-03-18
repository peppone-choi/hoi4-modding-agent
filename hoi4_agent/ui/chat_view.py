"""Chat view UI: message display and user input handling."""
import json
from pathlib import Path

import streamlit as st

from hoi4_agent.core.prompt import TOOLS, build_system_prompt
from hoi4_agent.core.scanner import ModContext
from hoi4_agent.tools.executor import ToolExecutor

_ERROR_PREFIXES = (
    "[오류]",
    "[도구 오류]",
    "[파일 없음]",
    "[디렉토리 없음]",
    "[결과 없음]",
    "[포트레잇 오류]",
    "[포트레잇 검색 오류]",
)


def render_chat(ctx: ModContext, mod_root: Path, config):
    _display_messages()
    _handle_input(ctx, mod_root, config)


def _display_messages():
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg.get("images"):
                for ip in msg["images"]:
                    if Path(ip).exists():
                        st.image(ip, width=200)
            st.markdown(msg["content"])


def _get_api_messages() -> list:
    """세션 내 tool_use/tool_result 전체를 보존하는 API 메시지 반환.

    세션 전환 시 자동 재초기화. 세션 내에서는 도구 호출 컨텍스트가
    턴 간에 유실되지 않아 Claude가 실제 실행 이력을 정확히 참조한다.
    """
    current_session = st.session_state.get("current_session_id")
    if (
        "api_messages" not in st.session_state
        or st.session_state.get("_api_msg_session") != current_session
    ):
        st.session_state.api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages
        ]
        st.session_state._api_msg_session = current_session
    return st.session_state.api_messages


def _serialize_content(content) -> list[dict]:
    result = []
    for blk in content:
        if blk.type == "text":
            result.append({"type": "text", "text": blk.text})
        elif blk.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": blk.id,
                "name": blk.name,
                "input": blk.input,
            })
        elif hasattr(blk, "model_dump"):
            result.append(blk.model_dump())
    return result


def _build_tool_summary(tool_log: list[dict]) -> str:
    if not tool_log:
        return ""
    lines = ["\n\n---", "📋 **도구 실행 기록**"]
    for entry in tool_log:
        icon = "✅" if entry["success"] else "❌"
        preview = entry["result"][:80].replace("\n", " ")
        lines.append(f"- {icon} `{entry['tool']}` → {preview}")
    return "\n".join(lines)


def _handle_input(ctx: ModContext, mod_root: Path, config):
    prompt = st.chat_input("무엇을 할까요?")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.chat_manager.save_message(
        st.session_state.current_session_id, "user", prompt
    )
    with st.chat_message("user"):
        st.markdown(prompt)

    if config.ai_provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=config.anthropic_key)
        model = config.default_model
    else:
        from hoi4_agent.core.ollama_client import OllamaClient
        client = OllamaClient(base_url=config.ollama_base_url, model=config.ollama_model)
        model = config.ollama_model
    
    mcp_mgr = st.session_state.get("mcp_manager")
    executor = ToolExecutor(
        mod_root=mod_root,
        gemini_key=config.gemini_key,
        mcp_manager=mcp_mgr,
        portrait_bg_top=config.portrait_bg_top,
        portrait_bg_bottom=config.portrait_bg_bottom,
        portrait_bg_gradient=config.portrait_bg_gradient,
        portrait_scanlines_enabled=config.portrait_scanlines_enabled,
    )
    system_prompt = build_system_prompt(ctx)

    mcp_tools = mcp_mgr.discover_tools() if mcp_mgr and mcp_mgr.available else []
    all_tools = TOOLS + mcp_tools

    api_msgs = _get_api_messages()
    api_msgs.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        images: list[str] = []
        full = ""
        tool_log: list[dict] = []
        rounds = 0

        try:
            while rounds < config.max_tool_rounds:
                rounds += 1

                with client.messages.stream(
                    model=model,
                    max_tokens=config.max_tokens,
                    system=system_prompt,
                    tools=all_tools,
                    messages=api_msgs,
                    tool_choice={"type": "any"} if rounds == 1 else {"type": "auto"},
                ) as stream:
                    resp_text = st.write_stream(stream.text_stream)
                    resp = stream.get_final_message()

                streamed = ""
                if isinstance(resp_text, str):
                    streamed = resp_text
                full += streamed

                tool_results = []
                for blk in resp.content:
                    if blk.type == "tool_use":
                        preview = json.dumps(blk.input, ensure_ascii=False)[
                            :120
                        ]
                        st.caption(f"🔧 {blk.name}({preview})")
                        result = executor.execute(blk.name, blk.input)

                        is_error = result.startswith(_ERROR_PREFIXES)
                        tool_log.append({
                            "tool": blk.name,
                            "input": json.dumps(
                                blk.input, ensure_ascii=False
                            )[:200],
                            "result": result[:500],
                            "success": not is_error,
                        })

                        if result.startswith("IMAGE:"):
                            relative_path = result[6:].strip()
                            absolute_path = Path(relative_path)
                            if not absolute_path.is_absolute():
                                absolute_path = mod_root / relative_path
                            
                            if absolute_path.exists():
                                st.image(str(absolute_path), width=200)
                                images.append(str(absolute_path))
                                result = f"[이미지 표시됨] {relative_path}"
                            else:
                                result = f"[이미지 없음] {relative_path} (찾은 경로: {absolute_path})"

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": blk.id,
                                "content": result[:10000],
                            }
                        )

                # tool_use + tool_result를 직렬화 — 다음 턴에서 도구 실행 이력 유지
                api_msgs.append({
                    "role": "assistant",
                    "content": _serialize_content(resp.content),
                })

                if resp.stop_reason == "tool_use" and tool_results:
                    api_msgs.append({"role": "user", "content": tool_results})
                else:
                    break

        except anthropic.APIConnectionError:
            full += "\n\n❌ **API 연결 실패** — 인터넷 연결을 확인하세요."
            st.error("Anthropic API 연결 실패. 인터넷 연결을 확인하세요.")
        except anthropic.RateLimitError:
            full += "\n\n❌ **API 요청 제한** — 잠시 후 다시 시도하세요."
            st.error("API 요청 제한에 도달했습니다. 잠시 후 다시 시도하세요.")
        except anthropic.APIStatusError as exc:
            full += f"\n\n❌ **API 오류 ({exc.status_code})** — {exc.message}"
            st.error(f"API 오류 ({exc.status_code}): {exc.message}")

        if tool_log:
            summary = _build_tool_summary(tool_log)
            full += summary
            st.markdown(summary)

    if full.strip():
        st.session_state.messages.append(
            {"role": "assistant", "content": full, "images": images}
        )
        st.session_state.chat_manager.save_message(
            st.session_state.current_session_id,
            "assistant",
            full,
            images,
            tool_history=tool_log if tool_log else None,
        )
