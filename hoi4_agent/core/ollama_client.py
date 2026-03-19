"""
Ollama client wrapper that mimics Anthropic's streaming API interface.
Uses Ollama's OpenAI-compatible API for tool calling support.
"""
import json
import logging
from typing import Iterator

import requests

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format='[OLLAMA_DEBUG] %(message)s'
)


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
            logger.debug(f"Raw chunk: {json.dumps(chunk, ensure_ascii=False)}")
            
            if chunk.get("done"):
                self._done = True
                logger.debug(f"Final chunk (done=true): {json.dumps(chunk, ensure_ascii=False)}")
                break
            
            message = chunk.get("message", {})
            content = message.get("content", "")
            thinking = message.get("thinking", "")
            
            if self._supports_tools and "tool_calls" in message:
                logger.debug(f"Tool calls detected: {json.dumps(message['tool_calls'], ensure_ascii=False)}")
                self._tool_calls.extend(message["tool_calls"])
            
            text_output = content or thinking
            if text_output:
                self._final_content.append(text_output)
                yield text_output
    
    def get_final_message(self):
        logger.debug(f"get_final_message() called - tool_calls count: {len(self._tool_calls)}")
        if self._tool_calls:
            logger.debug(f"Tool calls structure: {json.dumps(self._tool_calls, ensure_ascii=False)}")
        
        class ToolUseBlock:
            def __init__(self, tool_call):
                self.type = "tool_use"
                self.id = tool_call.get("id", "")
                self.name = tool_call["function"]["name"]
                args = tool_call["function"]["arguments"]
                self.input = json.loads(args) if isinstance(args, str) else args
        
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
                    tool_use_blocks = []
                    tool_result_blocks = []
                    for block in msg["content"]:
                        if block.get("type") == "tool_result":
                            tool_result_blocks.append(block)
                        elif block.get("type") == "tool_use":
                            tool_use_blocks.append(block)
                        elif block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    
                    if msg.get("role") == "assistant" and tool_use_blocks:
                        ollama_tool_calls = []
                        for blk in tool_use_blocks:
                            ollama_tool_calls.append({
                                "function": {
                                    "name": blk["name"],
                                    "arguments": blk["input"],
                                }
                            })
                        ollama_messages.append({
                            "role": "assistant",
                            "content": " ".join(text_parts) if text_parts else "",
                            "tool_calls": ollama_tool_calls,
                        })
                    elif tool_result_blocks:
                        for blk in tool_result_blocks:
                            ollama_messages.append({
                                "role": "tool",
                                "content": blk.get("content", ""),
                            })
                        if text_parts:
                            ollama_messages.append({
                                "role": msg["role"],
                                "content": " ".join(text_parts),
                            })
                    elif text_parts:
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
                    "num_predict": max_tokens + 2048,  # Increased from +1024 to +2048 for qwen3.5:4b thinking budget
                }
            }
            
            if tools:
                payload["tools"] = anthropic_to_openai_tools(tools)
                logger.debug(f"Sending tools to Ollama: {json.dumps(payload['tools'], ensure_ascii=False)}")
            
            logger.debug(f"Ollama request payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
            
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
