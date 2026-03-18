"""
Ollama client wrapper that mimics Anthropic's streaming API interface.
"""
import json
from typing import Iterator

import requests


class OllamaStreamWrapper:
    def __init__(self, response_iterator: Iterator[dict]):
        self._iterator = response_iterator
        self._final_content = []
        self._done = False
    
    def text_stream(self) -> Iterator[str]:
        for chunk in self._iterator:
            if chunk.get("done"):
                self._done = True
                break
            
            content = chunk.get("message", {}).get("content", "")
            if content:
                self._final_content.append(content)
                yield content
    
    def get_final_message(self):
        class FinalMessage:
            def __init__(self, content_text: str):
                self.content = [type('Block', (), {'type': 'text', 'text': content_text})]
                self.stop_reason = "end_turn"
        
        return FinalMessage("".join(self._final_content))


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:70b"):
        self.base_url = base_url.rstrip("/")
        self.model = model
    
    class Messages:
        def __init__(self, client):
            self.client = client
        
        def stream(self, model: str, max_tokens: int, system: str, messages: list, tools: list | None = None, tool_choice: dict | None = None):
            ollama_messages = []
            
            if system:
                ollama_messages.append({"role": "system", "content": system})
            
            for msg in messages:
                ollama_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            payload = {
                "model": self.client.model,
                "messages": ollama_messages,
                "stream": True,
                "options": {
                    "num_predict": max_tokens,
                }
            }
            
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
            
            return OllamaStreamWrapper(response_iterator())
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:70b"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.messages = self.Messages(self)
