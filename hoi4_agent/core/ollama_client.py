"""
Ollama client wrapper that mimics Anthropic's streaming API interface.
Uses Ollama's OpenAI-compatible API for tool calling support.
"""
import json
from typing import Iterator

import requests


def anthropic_to_openai_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schema to OpenAI function schema."""
    openai_tools = []
    
    for tool in anthropic_tools:
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"]
            }
        }
        openai_tools.append(openai_tool)
    
    return openai_tools


class OllamaStreamWrapper:
    def __init__(self, response_iterator: Iterator[dict], supports_tools: bool = False):
        self._iterator = response_iterator
        self._final_content = []
        self._tool_calls = []
        self._done = False
        self._supports_tools = supports_tools
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
    
    def text_stream(self) -> Iterator[str]:
        for chunk in self._iterator:
            if chunk.get("done"):
                self._done = True
                break
            
            message = chunk.get("message", {})
            content = message.get("content", "")
            
            if self._supports_tools and "tool_calls" in message:
                self._tool_calls.extend(message["tool_calls"])
            
            if content:
                self._final_content.append(content)
                yield content
    
    def get_final_message(self):
        class ToolUseBlock:
            def __init__(self, tool_call):
                self.type = "tool_use"
                self.id = tool_call.get("id", "")
                self.name = tool_call["function"]["name"]
                self.input = json.loads(tool_call["function"]["arguments"])
        
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


class OllamaClient:
    class Messages:
        def __init__(self, client):
            self.client = client
        
        def stream(self, model: str, max_tokens: int, system: str | list, messages: list, tools: list | None = None, tool_choice: dict | None = None):
            ollama_messages = []
            
            if system:
                if isinstance(system, list):
                    system_text = " ".join(
                        block.get("text", "") for block in system if isinstance(block, dict)
                    )
                else:
                    system_text = system
                ollama_messages.append({"role": "system", "content": system_text})
            
            for msg in messages:
                if isinstance(msg.get("content"), list):
                    text_parts: list[str] = []
                    for block in msg["content"]:
                        if block.get("type") == "tool_result":
                            ollama_messages.append({
                                "role": "tool",
                                "tool_name": block.get("tool_name", ""),
                                "content": block.get("content", ""),
                            })
                        elif block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    if text_parts:
                        ollama_messages.append({
                            "role": msg["role"],
                            "content": " ".join(text_parts),
                        })
                elif msg.get("role") == "assistant" and "tool_calls" in msg:
                    ollama_messages.append(msg)
                else:
                    ollama_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })
            
            payload = {
                "model": self.client.model,
                "messages": ollama_messages,
                "stream": True,
                "options": {
                    "num_predict": max_tokens,
                }
            }
            
            if tools:
                payload["tools"] = anthropic_to_openai_tools(tools)
            
            response = requests.post(
                f"{self.client.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=300
            )
            response.raise_for_status()
            
            def response_iterator():
                for line in response.iter_lines():
                    if line:
                        yield json.loads(line)
            
            return OllamaStreamWrapper(response_iterator(), supports_tools=tools is not None)
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:70b"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.messages = self.Messages(self)
