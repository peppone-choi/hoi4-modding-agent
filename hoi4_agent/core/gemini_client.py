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
                    parts.append(types.Part.from_function_response(
                        name=block.get("tool_name", "unknown"),
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
            for part in chunk.candidates[0].content.parts:
                if part.text:
                    self._final_content.append(part.text)
                    yield part.text
                elif part.function_call:
                    fc = part.function_call
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


class GeminiClient:
    class Messages:
        def __init__(self, client):
            self.client = client

        def stream(self, model: str, max_tokens: int, system: str | list,
                   messages: list, tools: list | None = None,
                   tool_choice: dict | None = None):
            system_text, contents = _build_gemini_messages(system, messages)

            config = types.GenerateContentConfig(
                system_instruction=system_text if system_text else None,
                max_output_tokens=max_tokens,
                temperature=0.7,
            )

            if tools:
                gemini_tools = anthropic_to_gemini_tools(tools)
                config.tools = gemini_tools
                config.automatic_function_calling = types.AutomaticFunctionCallingConfig(
                    disable=True
                )

            response_stream = self.client._genai.models.generate_content_stream(
                model=self.client.model,
                contents=contents,
                config=config,
            )

            return GeminiStreamWrapper(response_stream, supports_tools=tools is not None)

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview"):
        self._genai = genai.Client(api_key=api_key)
        self.model = model
        self.messages = self.Messages(self)
