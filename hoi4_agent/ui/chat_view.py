"""Chat view UI: message display and user input handling."""
import asyncio
import json
from pathlib import Path

import streamlit as st

from hoi4_agent.core.orchestration import execute_sonnet_parallel
from hoi4_agent.core.prompt import TOOLS, build_system_prompt, build_system_prompt_simple
from hoi4_agent.core.scanner import ModContext
from hoi4_agent.core.task_decomposer import TaskDecomposer, ExecutionStrategy
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

_decomposer = TaskDecomposer()


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
            entry = {"type": "text", "text": blk.text}
            if hasattr(blk, "thought_signature") and blk.thought_signature:
                entry["thought_signature"] = blk.thought_signature
            result.append(entry)
        elif blk.type == "tool_use":
            entry = {
                "type": "tool_use",
                "id": blk.id,
                "name": blk.name,
                "input": blk.input,
            }
            if hasattr(blk, "thought_signature") and blk.thought_signature:
                entry["thought_signature"] = blk.thought_signature
            result.append(entry)
        elif hasattr(blk, "model_dump"):
            result.append(blk.model_dump())
    return result


_CACHE_EPHEMERAL = {"type": "ephemeral"}


def _prepare_cached_params(system_prompt: str, tools: list[dict]) -> tuple[list, list]:
    cached_system = [
        {"type": "text", "text": system_prompt, "cache_control": _CACHE_EPHEMERAL}
    ]
    if tools:
        cached_tools = [*tools[:-1], {**tools[-1], "cache_control": _CACHE_EPHEMERAL}]
    else:
        cached_tools = []
    return cached_system, cached_tools


def _with_history_cache(messages: list[dict]) -> list[dict]:
    if len(messages) < 2:
        return messages
    msgs = [*messages[:-1]]
    last = messages[-1].copy()
    content = last.get("content")
    if isinstance(content, str):
        last["content"] = [
            {"type": "text", "text": content, "cache_control": _CACHE_EPHEMERAL}
        ]
    elif isinstance(content, list) and content:
        last["content"] = [
            *content[:-1],
            {**content[-1], "cache_control": _CACHE_EPHEMERAL},
        ]
    msgs.append(last)
    return msgs


def _build_tool_summary(tool_log: list[dict]) -> str:
    if not tool_log:
        return ""
    lines = ["\n\n---", "📋 **도구 실행 기록**"]
    for entry in tool_log:
        icon = "✅" if entry["success"] else "❌"
        preview = entry["result"][:80].replace("\n", " ")
        lines.append(f"- {icon} `{entry['tool']}` → {preview}")
    return "\n".join(lines)


def _select_model(config, prompt: str) -> str:
    """TaskDecomposer 기반 모델 라우팅.
    
    유저가 수동으로 모델을 선택했으면 그대로 사용.
    '자동' 모드일 때만 TaskDecomposer가 Haiku/Sonnet 결정.
    Opus 에스컬레이션이 활성화되어 있으면 무조건 Opus.
    """
    if config.ai_provider == "ollama":
        return config.ollama_model
    if config.ai_provider == "gemini":
        return config.gemini_model
    if config.ai_provider == "openai":
        return config.openai_model
    if config.ai_provider != "anthropic":
        return config.ollama_model
    
    # Opus 에스컬레이션 — 최우선
    if st.session_state.get("escalated_to_opus", False):
        return config.opus_model
    
    # 유저가 수동 선택한 경우
    model_selection = st.session_state.get("model_selection", "자동 (Sonnet 기본) - 권장")
    if "Haiku" in model_selection:
        return config.haiku_model
    if "Sonnet" in model_selection:
        return config.sonnet_model
    if "Opus" in model_selection:
        return config.opus_model
    
    # 자동 모드: TaskDecomposer가 판단
    # Haiku 연속 실패 중이면 Haiku 스킵
    if st.session_state.get("haiku_consecutive_failures", 0) >= 2:
        return config.sonnet_model
    
    analysis = _decomposer.analyze(prompt)
    if analysis.strategy == ExecutionStrategy.HAIKU_WORKER:
        return config.haiku_model
    
    return config.sonnet_model


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
    elif config.ai_provider == "gemini":
        from hoi4_agent.core.gemini_client import GeminiClient
        client = GeminiClient(api_key=config.gemini_key, model=config.gemini_model)
    elif config.ai_provider == "openai":
        from hoi4_agent.core.openai_client import OpenAIClient
        client = OpenAIClient(api_key=config.openai_key, model=config.openai_model)
    else:
        from hoi4_agent.core.ollama_client import OllamaClient
        client = OllamaClient(base_url=config.ollama_base_url, model=config.ollama_model)
    
    # 세션 상태 초기화
    if "consecutive_failures" not in st.session_state:
        st.session_state.consecutive_failures = 0
    if "sonnet_parallel_count" not in st.session_state:
        st.session_state.sonnet_parallel_count = 1
    if "escalated_to_opus" not in st.session_state:
        st.session_state.escalated_to_opus = False
    if "haiku_consecutive_failures" not in st.session_state:
        st.session_state.haiku_consecutive_failures = 0
    
    # TaskDecomposer 기반 모델 선택
    model = _select_model(config, prompt)
    used_haiku = (model == config.haiku_model)
    
    if st.session_state.get("escalated_to_opus", False):
        st.info("🚀 **Opus 모드 활성화** (Sonnet 12회 실패 → 자동 전환)")
    elif used_haiku:
        st.caption("⚡ 단순 작업 감지 → Haiku 워커")
    
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
    if config.use_simple_prompt:
        system_prompt = build_system_prompt_simple(ctx)
    else:
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
        has_errors = False
        gemini_force_text = False

        try:
            while rounds < config.max_tool_rounds:
                rounds += 1
                
                streamed = ""
                use_sonnet_parallel = (
                    config.ai_provider == "anthropic"
                    and model == config.sonnet_model
                    and st.session_state.sonnet_parallel_count > 1
                )
                
                sys_param = system_prompt
                tools_param = all_tools
                call_msgs = api_msgs
                if config.ai_provider == "anthropic":
                    sys_param, tools_param = _prepare_cached_params(system_prompt, all_tools)
                    call_msgs = _with_history_cache(api_msgs)

                if use_sonnet_parallel:
                    count = st.session_state.sonnet_parallel_count
                    st.caption(f"🔄 Sonnet {count}개 병렬 실행 중...")
                    resp = asyncio.run(
                        execute_sonnet_parallel(
                            client=client,
                            model=model,
                            system_prompt=sys_param,
                            tools=tools_param,
                            messages=call_msgs,
                            max_tokens=config.max_tokens,
                            count=count,
                        )
                    )
                    for blk in resp.content:
                        if blk.type == "text":
                            streamed += blk.text
                    if streamed:
                        st.markdown(streamed)
                else:
                    stream_kwargs = dict(
                        model=model,
                        max_tokens=config.max_tokens,
                        system=sys_param,
                        tools=tools_param,
                        messages=call_msgs,
                        tool_choice={"type": "auto"},
                    )
                    if gemini_force_text and config.ai_provider == "gemini":
                        stream_kwargs["force_text"] = True

                    with client.messages.stream(**stream_kwargs) as stream:
                        resp_text = st.write_stream(stream.text_stream)
                        resp = stream.get_final_message()
                    if isinstance(resp_text, str):
                        streamed = resp_text
                
                full += streamed

                cache_usage = getattr(resp, "usage", None)
                if config.ai_provider == "anthropic" and cache_usage is not None:
                    cache_read = getattr(cache_usage, "cache_read_input_tokens", 0) or 0
                    cache_write = getattr(cache_usage, "cache_creation_input_tokens", 0) or 0
                    if cache_read > 0:
                        st.caption(f"💾 캐시 히트: {cache_read:,} 토큰 (90% 절감)")
                    elif cache_write > 0:
                        st.caption(f"💾 캐시 생성: {cache_write:,} 토큰")

                tool_results = []
                for blk in resp.content:
                    if blk.type == "tool_use":
                        preview = json.dumps(blk.input, ensure_ascii=False)[
                            :120
                        ]
                        st.caption(f"🔧 {blk.name}({preview})")
                        result = executor.execute(blk.name, blk.input)

                        is_error = result.startswith(_ERROR_PREFIXES)
                        if is_error:
                            has_errors = True
                        
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
                                "tool_name": blk.name,
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
                    if rounds >= config.max_tool_rounds:
                        if config.ai_provider == "gemini" and not gemini_force_text:
                            gemini_force_text = True
                            config.max_tool_rounds += 1
                        else:
                            st.warning(f"⚠️ 도구 호출 {rounds}회 도달. 자동 이어서 진행합니다...")
                            config.max_tool_rounds += 50
                else:
                    break
            
            # === 에러 추적: Haiku / Sonnet 분리 ===
            if config.ai_provider == "anthropic":
                if has_errors:
                    if used_haiku:
                        # Haiku 실패 → 카운터 증가, 2회 연속 실패면 Sonnet으로 전환
                        st.session_state.haiku_consecutive_failures = (
                            st.session_state.get("haiku_consecutive_failures", 0) + 1
                        )
                        if st.session_state.haiku_consecutive_failures >= 2:
                            st.caption("⚠️ Haiku 연속 실패 → 다음부터 Sonnet 사용")
                    else:
                        # Sonnet 실패 → 기존 점진적 병렬 에스컬레이션
                        st.session_state.consecutive_failures += 1
                        consecutive_failures = st.session_state.consecutive_failures
                        
                        if consecutive_failures == 1:
                            st.session_state.sonnet_parallel_count = 2
                            st.caption("⚠️ 오류 감지 → 다음 요청부터 Sonnet 2개 병렬 실행")
                        elif consecutive_failures == 3:
                            st.session_state.sonnet_parallel_count = 4
                            st.caption("⚠️ 오류 지속 → 다음 요청부터 Sonnet 4개 병렬 실행")
                        elif consecutive_failures == 7:
                            st.session_state.sonnet_parallel_count = 5
                            st.caption("⚠️ 오류 지속 → 다음 요청부터 Sonnet 5개 병렬 실행")
                        elif consecutive_failures >= 12:
                            st.session_state.escalated_to_opus = True
                            st.warning("🚀 Sonnet 12회 실패 → 다음 요청부터 **Opus** 자동 전환")
                else:
                    # 성공 → 모든 실패 카운터 리셋
                    if used_haiku:
                        st.session_state.haiku_consecutive_failures = 0
                    else:
                        st.session_state.consecutive_failures = 0
                        st.session_state.sonnet_parallel_count = 1
                        if st.session_state.get("escalated_to_opus", False):
                            st.session_state.escalated_to_opus = False
                            st.success("✅ 성공 → Sonnet으로 자동 복귀")
                        # Sonnet 성공 → Haiku 실패 카운터도 리셋 (복구 허용)
                        st.session_state.haiku_consecutive_failures = 0

        except Exception as exc:
            exc_type = type(exc).__name__
            try:
                import anthropic as _anthropic
                if isinstance(exc, _anthropic.APIConnectionError):
                    full += "\n\n❌ **API 연결 실패** — 인터넷 연결을 확인하세요."
                    st.error("Anthropic API 연결 실패. 인터넷 연결을 확인하세요.")
                elif isinstance(exc, _anthropic.RateLimitError):
                    full += "\n\n❌ **API 요청 제한** — 잠시 후 다시 시도하세요."
                    st.error("API 요청 제한에 도달했습니다. 잠시 후 다시 시도하세요.")
                elif isinstance(exc, _anthropic.APIStatusError):
                    full += f"\n\n❌ **API 오류 ({exc.status_code})** — {exc.message}"
                    st.error(f"API 오류 ({exc.status_code}): {exc.message}")
                else:
                    full += f"\n\n❌ **오류** ({exc_type}) — {exc}"
                    st.error(f"오류 ({exc_type}): {exc}")
            except ImportError:
                full += f"\n\n❌ **오류** ({exc_type}) — {exc}"
                st.error(f"오류 ({exc_type}): {exc}")

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
