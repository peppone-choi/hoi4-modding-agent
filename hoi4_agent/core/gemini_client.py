"""
Gemini client wrapper that mimics Anthropic's streaming API interface.
Uses google-genai SDK (NOT the deprecated google-generativeai).

pip install -U google-genai
"""
import base64
import json
from typing import Iterator

from google import genai
from google.genai import types


def anthropic_to_gemini_tools(anthropic_tools: list[dict]) -> list[types.Tool]:
    declarations = []
    for tool in anthropic_tools:
        schema = tool.get("input_schema", {})
        properties = schema.get("properties", {})
        cleaned_props = {}
        for k, v in properties.items():
            cleaned = {key: val for key, val in v.items() if key != "additionalProperties"}
            cleaned_props[k] = cleaned

        declarations.append(types.FunctionDeclaration(
            name=tool["name"],
            description=tool.get("description", ""),
            parameters={
                "type": "object",
                "properties": cleaned_props,
                "required": schema.get("required", []),
            } if cleaned_props else None,
        ))
    return [types.Tool(function_declarations=declarations)]


def _build_gemini_messages(system: str | list, messages: list) -> tuple[str, list]:
    if isinstance(system, list):
        system_text = " ".join(
            block.get("text", "") for block in system if isinstance(block, dict)
        )
    else:
        system_text = system or ""

    contents = []
    tool_id_to_name: dict[str, str] = {}
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"

        if isinstance(msg.get("content"), list):
            parts = []
            for block in msg["content"]:
                if block.get("type") == "text":
                    part = types.Part.from_text(text=block["text"])
                    sig = block.get("thought_signature")
                    if sig:
                        part.thought_signature = base64.b64decode(sig)
                    parts.append(part)
                elif block.get("type") == "tool_use":
                    tool_id_to_name[block.get("id", "")] = block["name"]
                    part = types.Part.from_function_call(
                        name=block["name"],
                        args=block["input"],
                    )
                    sig = block.get("thought_signature")
                    if sig:
                        part.thought_signature = base64.b64decode(sig)
                    else:
                        part.thought_signature = b'skip_thought_signature_validator'
                    parts.append(part)
                elif block.get("type") == "tool_result":
                    resolved_name = tool_id_to_name.get(
                        block.get("tool_use_id", ""), "unknown"
                    )
                    parts.append(types.Part.from_function_response(
                        name=resolved_name,
                        response={"result": block.get("content", "")},
                    ))
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        elif isinstance(msg.get("content"), str):
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg["content"])],
            ))

    return system_text, contents


class GeminiStreamWrapper:
    def __init__(self, response_stream, supports_tools: bool = False):
        self._stream = response_stream
        self._final_content = []
        self._tool_calls = []
        self._supports_tools = supports_tools
        self._consumed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def text_stream(self) -> Iterator[str]:
        self._consumed = True
        for chunk in self._stream:
            if not chunk.candidates:
                continue
            parts = chunk.candidates[0].content.parts if chunk.candidates[0].content else []
            for part in (parts or []):
                if part.text:
                    self._final_content.append(part.text)
                    yield part.text
                elif part.function_call:
                    fc = part.function_call
                    print(f"[GEMINI] 도구 호출 감지: {fc.name}({dict(fc.args) if fc.args else {}})")
                    sig = None
                    if hasattr(part, 'thought_signature') and part.thought_signature:
                        sig = base64.b64encode(part.thought_signature).decode('utf-8')
                    self._tool_calls.append({
                        "id": f"gemini_{fc.name}_{len(self._tool_calls)}",
                        "function": {
                            "name": fc.name,
                            "arguments": dict(fc.args) if fc.args else {},
                        },
                        "thought_signature": sig,
                    })

    def get_final_message(self):
        if not self._consumed:
            for _ in self.text_stream():
                pass
        print(f"[GEMINI] get_final_message() — tool_calls: {len(self._tool_calls)}, text_len: {sum(len(t) for t in self._final_content)}")

        class ToolUseBlock:
            def __init__(self, tool_call):
                self.type = "tool_use"
                self.id = tool_call.get("id", "")
                self.name = tool_call["function"]["name"]
                self.input = tool_call["function"]["arguments"]
                self.thought_signature = tool_call.get("thought_signature")

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
        return FinalMessage(text, self._tool_calls)


GEMINI_FALLBACK_CHAIN = [
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-lite",
    "gemini-2-flash-lite",
]


class GeminiClient:
    class Messages:
        def __init__(self, client):
            self.client = client

        def stream(self, model: str, max_tokens: int, system: str | list,
                   messages: list, tools: list | None = None,
                   tool_choice: dict | None = None,
                   force_text: bool = False):
            system_text, contents = _build_gemini_messages(system, messages)

            config = types.GenerateContentConfig(
                system_instruction=system_text if system_text else None,
                max_output_tokens=max_tokens,
                temperature=0.7,
            )

            if force_text:
                print("[GEMINI] 강제 텍스트 모드 — 도구 비활성화, 결과 보고 강제")
            elif tools:
                gemini_tools = anthropic_to_gemini_tools(tools)
                config.tools = gemini_tools

                has_tool_results = any(
                    isinstance(m.get("content"), list) and
                    any(b.get("type") == "tool_result" for b in m["content"])
                    for m in messages
                )
                mode = "AUTO" if has_tool_results else "ANY"
                config.tool_config = types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode=mode)
                )
                config.automatic_function_calling = types.AutomaticFunctionCallingConfig(
                    disable=True
                )
                tool_names = [t["name"] for t in tools]
                print(f"[GEMINI] {len(tools)}개 도구 전달 (mode={mode}): {tool_names[:10]}")
            else:
                print("[GEMINI] 도구 없이 호출됨!")

            models_to_try = [self.client.model]
            for fb in GEMINI_FALLBACK_CHAIN:
                if fb != self.client.model and fb not in models_to_try:
                    models_to_try.append(fb)

            last_error = None
            for try_model in models_to_try:
                try:
                    response_stream = self.client._genai.models.generate_content_stream(
                        model=try_model,
                        contents=contents,
                        config=config,
                    )
                    if try_model != self.client.model:
                        print(f"[GEMINI] 429 폴백: {self.client.model} → {try_model}")
                    return GeminiStreamWrapper(response_stream, supports_tools=tools is not None)
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        print(f"[GEMINI] {try_model} TPM 초과, 다음 모델 시도...")
                        last_error = e
                        continue
                    raise

            raise last_error or RuntimeError("All Gemini models exhausted (429)")

    def __init__(self, api_key: str, model: str = "gemini-2.5-pro"):
        self._genai = genai.Client(api_key=api_key)
        self.model = model
        self.messages = self.Messages(self)
