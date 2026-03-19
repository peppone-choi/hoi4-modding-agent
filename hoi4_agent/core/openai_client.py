"""
OpenAI client wrapper that mimics Anthropic's streaming API interface.
Uses openai Python SDK v1.x+.

pip install -U openai
"""
import json
from collections import defaultdict
from typing import Iterator

from openai import OpenAI


def anthropic_to_openai_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schema to OpenAI function schema."""
    openai_tools = []
    for tool in anthropic_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            }
        })
    return openai_tools


def _build_openai_messages(system: str | list, messages: list) -> list[dict]:
    """Convert Anthropic-style messages to OpenAI messages format."""
    openai_msgs = []

    # System prompt
    if system:
        if isinstance(system, list):
            system_text = " ".join(
                block.get("text", "") for block in system if isinstance(block, dict)
            )
        else:
            system_text = system
        if system_text:
            openai_msgs.append({"role": "system", "content": system_text})

    for msg in messages:
        if isinstance(msg.get("content"), list):
            text_parts = []
            tool_use_blocks = []
            tool_result_blocks = []

            for block in msg["content"]:
                if block.get("type") == "tool_result":
                    tool_result_blocks.append(block)
                elif block.get("type") == "tool_use":
                    tool_use_blocks.append(block)
                elif block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

            # Assistant message with tool_use → OpenAI format
            if msg.get("role") == "assistant" and tool_use_blocks:
                openai_tool_calls = []
                for blk in tool_use_blocks:
                    openai_tool_calls.append({
                        "id": blk.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": blk["name"],
                            "arguments": json.dumps(blk["input"], ensure_ascii=False),
                        }
                    })
                openai_msgs.append({
                    "role": "assistant",
                    "content": " ".join(text_parts) if text_parts else None,
                    "tool_calls": openai_tool_calls,
                })
            # User message with tool_result → OpenAI tool messages
            elif tool_result_blocks:
                for blk in tool_result_blocks:
                    openai_msgs.append({
                        "role": "tool",
                        "tool_call_id": blk.get("tool_use_id", ""),
                        "content": blk.get("content", ""),
                    })
                if text_parts:
                    openai_msgs.append({
                        "role": msg["role"],
                        "content": " ".join(text_parts),
                    })
            elif text_parts:
                openai_msgs.append({
                    "role": msg["role"],
                    "content": " ".join(text_parts),
                })
        else:
            openai_msgs.append({
                "role": msg["role"],
                "content": msg.get("content", ""),
            })

    return openai_msgs


class OpenAIStreamWrapper:
    def __init__(self, stream, supports_tools: bool = False):
        self._stream = stream
        self._final_content = []
        self._tool_calls_acc: dict[int, dict] = defaultdict(
            lambda: {"id": None, "function": {"name": None, "arguments": ""}}
        )
        self._supports_tools = supports_tools
        self._consumed = False
        self._finish_reason = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def text_stream(self) -> Iterator[str]:
        self._consumed = True
        for chunk in self._stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            self._finish_reason = chunk.choices[0].finish_reason

            # Text content
            if delta.content:
                self._final_content.append(delta.content)
                yield delta.content

            # Tool calls (streamed incrementally)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    acc = self._tool_calls_acc[idx]
                    if tc.id is not None:
                        acc["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            acc["function"]["name"] = tc.function.name
                        if tc.function.arguments:
                            acc["function"]["arguments"] += tc.function.arguments

    def get_final_message(self):
        # Consume stream if not already done
        if not self._consumed:
            for _ in self.text_stream():
                pass

        # Parse accumulated tool calls
        completed_calls = []
        for idx in sorted(self._tool_calls_acc.keys()):
            tc = self._tool_calls_acc[idx]
            args_str = tc["function"]["arguments"]
            try:
                parsed_args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                parsed_args = {"raw": args_str}
            completed_calls.append({
                "id": tc["id"] or f"call_{idx}",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": parsed_args,
                }
            })

        class ToolUseBlock:
            def __init__(self, tool_call):
                self.type = "tool_use"
                self.id = tool_call.get("id", "")
                self.name = tool_call["function"]["name"]
                self.input = tool_call["function"]["arguments"]

        class TextBlock:
            def __init__(self, text: str):
                self.type = "text"
                self.text = text

        class FinalMessage:
            def __init__(self, text: str, tool_calls: list):
                self.content = []
                if text:
                    self.content.append(TextBlock(text))
                for tc in tool_calls:
                    self.content.append(ToolUseBlock(tc))
                self.stop_reason = "end_turn" if not tool_calls else "tool_use"

        text = "".join(self._final_content)
        return FinalMessage(text, completed_calls)


OPENAI_FALLBACK_CHAIN = [
    "gpt-4o-mini",
    "gpt-4.1-nano",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4.1",
]


class OpenAIClient:
    class Messages:
        def __init__(self, client):
            self.client = client

        def stream(self, model: str, max_tokens: int, system: str | list,
                   messages: list, tools: list | None = None,
                   tool_choice: dict | None = None):
            openai_msgs = _build_openai_messages(system, messages)

            base_kwargs = {
                "messages": openai_msgs,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if tools:
                base_kwargs["tools"] = anthropic_to_openai_tools(tools)
                base_kwargs["tool_choice"] = "auto"

            models_to_try = [self.client.model]
            for fb in OPENAI_FALLBACK_CHAIN:
                if fb != self.client.model and fb not in models_to_try:
                    models_to_try.append(fb)

            last_error = None
            for try_model in models_to_try:
                try:
                    response_stream = self.client._openai.chat.completions.create(
                        model=try_model, **base_kwargs
                    )
                    if try_model != self.client.model:
                        print(f"[OPENAI] 429 폴백: {self.client.model} → {try_model}")
                    return OpenAIStreamWrapper(response_stream, supports_tools=tools is not None)
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "rate_limit" in err_str.lower():
                        print(f"[OPENAI] {try_model} rate limit, 다음 모델 시도...")
                        last_error = e
                        continue
                    raise

            raise last_error or RuntimeError("All OpenAI models exhausted (429)")

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self._openai = OpenAI(api_key=api_key)
        self.model = model
        self.messages = self.Messages(self)
