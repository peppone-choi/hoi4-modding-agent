"""MCP 클라이언트 — 외부 MCP 서버 연결 및 도구 실행.

커넥션 풀: 서버 프로세스를 상시 유지하여 매 호출마다 spawn 오버헤드 제거.
discover_tools()에서 연결을 열고, execute()에서 재사용, shutdown()에서 정리.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
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
        # 커넥션 풀: server_name → (ClientSession, AsyncExitStack)
        self._sessions: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._pool_ready = False

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
        self._tools = _run_async(self._discover_all_pooled())
        return self._tools

    async def _connect_server(self, name: str, config: MCPServerConfig) -> list[dict]:
        """단일 MCP 서버에 연결하고 세션을 풀에 보관."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        tools: list[dict] = []
        try:
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )
            stack = AsyncExitStack()
            streams = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(*streams))
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

            # 풀에 저장 — 프로세스가 살아있는 채로 유지
            self._sessions[name] = session
            self._stacks[name] = stack
        except Exception as exc:
            print(f"[MCP] {name} 연결 실패: {exc}")
        return tools

    async def _discover_all_pooled(self) -> list[dict]:
        """모든 MCP 서버에 병렬 연결하고 세션을 풀에 보관."""
        tasks = [
            self._connect_server(name, config)
            for name, config in self.configs.items()
        ]
        results = await asyncio.gather(*tasks)
        self._pool_ready = True

        tools: list[dict] = []
        for server_tools in results:
            tools.extend(server_tools)
        return tools

    def execute(self, tool_name: str, arguments: dict) -> str:
        server_name = self._tool_server_map.get(tool_name)
        if not server_name or server_name not in self.configs:
            return f"[MCP 오류] 알 수 없는 도구: {tool_name}"

        original = tool_name[len(f"mcp_{server_name}_"):]
        return _run_async(self._call_tool_pooled(server_name, original, arguments))

    async def _call_tool_pooled(
        self, server_name: str, tool_name: str, arguments: dict,
    ) -> str:
        """풀에 있는 기존 세션을 재사용하여 도구 호출. 실패 시 재연결."""
        session = self._sessions.get(server_name)

        # 세션이 없거나 죽었으면 재연결
        if session is None:
            config = self.configs[server_name]
            await self._connect_server(server_name, config)
            session = self._sessions.get(server_name)
            if session is None:
                return f"[MCP 오류] {server_name} 재연결 실패"

        try:
            result = await session.call_tool(tool_name, arguments)
            texts = [
                c.text for c in result.content
                if hasattr(c, "text")
            ]
            return "\n".join(texts) if texts else "[결과 없음]"
        except Exception as exc:
            # 세션이 죽었을 수 있음 — 재연결 1회 시도
            print(f"[MCP] {server_name}/{tool_name} 실패, 재연결 시도: {exc}")
            await self._reconnect_server(server_name)
            session = self._sessions.get(server_name)
            if session is None:
                return f"[MCP 오류] {tool_name}: 재연결 실패"

            try:
                result = await session.call_tool(tool_name, arguments)
                texts = [
                    c.text for c in result.content
                    if hasattr(c, "text")
                ]
                return "\n".join(texts) if texts else "[결과 없음]"
            except Exception as retry_exc:
                return f"[MCP 오류] {tool_name}: {retry_exc}"

    async def _reconnect_server(self, server_name: str) -> None:
        """기존 세션 정리 후 재연결."""
        # 기존 스택 정리
        old_stack = self._stacks.pop(server_name, None)
        self._sessions.pop(server_name, None)
        if old_stack:
            try:
                await old_stack.aclose()
            except Exception:
                pass

        config = self.configs.get(server_name)
        if config:
            await self._connect_server(server_name, config)

    async def _shutdown_all(self) -> None:
        """모든 MCP 서버 세션 정리."""
        for name, stack in list(self._stacks.items()):
            try:
                await stack.aclose()
            except Exception:
                pass
        self._sessions.clear()
        self._stacks.clear()
        self._pool_ready = False

    def shutdown(self) -> None:
        """동기 인터페이스: 모든 MCP 연결 정리."""
        if self._sessions:
            _run_async(self._shutdown_all())

    def __del__(self):
        """GC 시 안전하게 정리 시도."""
        try:
            if self._sessions:
                self.shutdown()
        except Exception:
            pass


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
