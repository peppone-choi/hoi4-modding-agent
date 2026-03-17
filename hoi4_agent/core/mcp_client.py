"""MCP 클라이언트 — 외부 MCP 서버 연결 및 도구 실행."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


class MCPManager:

    def __init__(self, configs: list[MCPServerConfig] | None = None):
        self.configs = {c.name: c for c in (configs or [])}
        self._tools: list[dict] = []
        self._tool_server_map: dict[str, str] = {}

    @classmethod
    def from_config_file(cls, path: Path) -> MCPManager:
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()

        configs: list[MCPServerConfig] = []
        for name, server in raw.items():
            env: dict[str, str] = {}
            for k, v in (server.get("env") or {}).items():
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    env[k] = os.environ.get(v[2:-1], "")
                else:
                    env[k] = str(v)
            configs.append(MCPServerConfig(
                name=name,
                command=server["command"],
                args=server.get("args", []),
                env=env,
            ))
        return cls(configs)

    @property
    def available(self) -> bool:
        return bool(self.configs) and _mcp_installed()

    def discover_tools(self) -> list[dict]:
        if self._tools or not self.available:
            return self._tools
        self._tools = _run_async(self._discover_all())
        return self._tools

    async def _discover_all(self) -> list[dict]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        tools: list[dict] = []
        for name, config in self.configs.items():
            try:
                params = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=config.env or None,
                )
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        for tool in result.tools:
                            prefixed = f"mcp_{name}_{tool.name}"
                            self._tool_server_map[prefixed] = name
                            tools.append({
                                "name": prefixed,
                                "description": f"[MCP:{name}] {tool.description or tool.name}",
                                "input_schema": tool.inputSchema,
                            })
            except Exception as exc:
                print(f"[MCP] {name} 연결 실패: {exc}")
        return tools

    def execute(self, tool_name: str, arguments: dict) -> str:
        server_name = self._tool_server_map.get(tool_name)
        if not server_name or server_name not in self.configs:
            return f"[MCP 오류] 알 수 없는 도구: {tool_name}"

        config = self.configs[server_name]
        original = tool_name[len(f"mcp_{server_name}_"):]
        return _run_async(self._call_tool(config, original, arguments))

    async def _call_tool(
        self, config: MCPServerConfig, tool_name: str, arguments: dict,
    ) -> str:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    texts = [
                        c.text for c in result.content
                        if hasattr(c, "text")
                    ]
                    return "\n".join(texts) if texts else "[결과 없음]"
        except Exception as exc:
            return f"[MCP 오류] {tool_name}: {exc}"


def _mcp_installed() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def _run_async(coro: Any) -> Any:
    """Streamlit 환경에서도 안전하게 async 실행."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        pass
    return loop.run_until_complete(coro)
