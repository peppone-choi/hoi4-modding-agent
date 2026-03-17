"""Chat view UI: message display and user input handling."""
import json
from pathlib import Path

import streamlit as st

from hoi4_agent.core.prompt import TOOLS, build_system_prompt
from hoi4_agent.core.scanner import ModContext
from hoi4_agent.tools.executor import ToolExecutor


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

    import anthropic

    client = anthropic.Anthropic(api_key=config.anthropic_key)
    executor = ToolExecutor(mod_root, gemini_key=config.gemini_key)
    system_prompt = build_system_prompt(ctx)
    api_msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    with st.chat_message("assistant"):
        with st.spinner("생각 중..."):
            images: list[str] = []
            full = ""

            while True:
                resp = client.messages.create(
                    model=config.default_model,
                    max_tokens=config.max_tokens,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=api_msgs,
                )
                tool_results = []
                for blk in resp.content:
                    if blk.type == "text":
                        full += blk.text
                    elif blk.type == "tool_use":
                        preview = json.dumps(blk.input, ensure_ascii=False)[
                            :120
                        ]
                        st.caption(f"🔧 {blk.name}({preview})")
                        result = executor.execute(blk.name, blk.input)
                        if result.startswith("IMAGE:"):
                            ip = result[6:]
                            if Path(ip).exists():
                                st.image(ip, width=200)
                                images.append(ip)
                            result = f"[이미지 표시됨] {ip}"
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": blk.id,
                                "content": result[:10000],
                            }
                        )

                if resp.stop_reason == "tool_use" and tool_results:
                    api_msgs.append(
                        {"role": "assistant", "content": resp.content}
                    )
                    api_msgs.append({"role": "user", "content": tool_results})
                else:
                    break

            st.markdown(full)

    st.session_state.messages.append(
        {"role": "assistant", "content": full, "images": images}
    )
    st.session_state.chat_manager.save_message(
        st.session_state.current_session_id, "assistant", full, images
    )
