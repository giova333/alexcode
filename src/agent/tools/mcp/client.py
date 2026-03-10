"""MCP server connection manager."""

from __future__ import annotations

import os
import re
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from agent.tools.mcp.adapter import MCPToolAdapter
from agent.tools.registry import ToolRegistry


class MCPManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}

    async def connect_all(self, server_configs: list[dict[str, Any]]) -> list[str]:
        """Connect to all configured MCP servers. Returns list of connected server names."""
        connected = []
        for config in server_configs:
            name = config.get("name", "unknown")
            try:
                await self._connect_one(config)
                connected.append(name)
            except BaseException as e:
                # Catch BaseException to handle CancelledError and ExceptionGroups
                # from async MCP transports. Log but don't fail — other servers may still work.
                print(f"Warning: Failed to connect MCP server '{name}': {e}")
        return connected

    async def _connect_one(self, config: dict[str, Any]) -> None:
        name = config.get("name", "unknown")
        transport = config.get("transport", "stdio")

        if transport == "stdio":
            session = await self._connect_stdio(config)
        elif transport in ("http", "streamable-http"):
            session = await self._connect_http(config)
        else:
            raise ValueError(f"Unsupported MCP transport: {transport}")

        self._sessions[name] = session

        # Discover and register tools
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            adapted = MCPToolAdapter(session, name, tool)
            self._registry.register(adapted)

    async def _connect_stdio(self, config: dict[str, Any]) -> ClientSession:
        # Interpolate env vars in the env dict
        env = config.get("env", {})
        resolved_env = {}
        for k, v in env.items():
            if isinstance(v, str):
                resolved_env[k] = re.sub(
                    r"\$\{(\w+)}", lambda m: os.environ.get(m.group(1), ""), v,
                )
            else:
                resolved_env[k] = v

        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env={**os.environ, **resolved_env} if resolved_env else None,
        )

        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        return session

    async def _connect_http(self, config: dict[str, Any]) -> ClientSession:
        url = config["url"]
        headers = config.get("headers", {})

        # Interpolate env vars in headers
        resolved_headers = {}
        for k, v in headers.items():
            if isinstance(v, str):
                resolved_headers[k] = re.sub(
                    r"\$\{(\w+)}", lambda m: os.environ.get(m.group(1), ""), v,
                )
            else:
                resolved_headers[k] = v

        read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
            streamablehttp_client(url, headers=resolved_headers if resolved_headers else None)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        return session

    async def close(self) -> None:
        """Close all MCP connections."""
        await self._exit_stack.aclose()
        self._sessions.clear()
