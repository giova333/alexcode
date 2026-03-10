"""MCP server connection manager."""

from __future__ import annotations

import logging
import os
import re
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.auth.oauth2 import OAuthClientProvider
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl

from agent.tools.mcp.adapter import MCPToolAdapter
from agent.tools.mcp.oauth import (
    CALLBACK_PORT,
    FileTokenStorage,
    open_browser_redirect,
    wait_for_callback,
)
from agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages connections to multiple MCP servers with automatic reconnection."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        # Per-server exit stacks so we can tear down / reconnect individually
        self._exit_stacks: dict[str, AsyncExitStack] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._configs: dict[str, dict[str, Any]] = {}

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
                logger.warning("Failed to connect MCP server '%s': %s", name, e)
                print(f"Warning: Failed to connect MCP server '{name}': {e}")
        return connected

    async def reconnect(self, server_name: str) -> ClientSession | None:
        """Reconnect a single MCP server. Returns new session or None on failure."""
        config = self._configs.get(server_name)
        if not config:
            logger.warning("No config for MCP server '%s', cannot reconnect", server_name)
            return None

        # Tear down the old connection
        await self._close_server(server_name)

        # Reconnect
        try:
            await self._connect_one(config)
            logger.info("Reconnected MCP server '%s'", server_name)
            return self._sessions.get(server_name)
        except BaseException as e:
            logger.warning("Failed to reconnect MCP server '%s': %s", server_name, e)
            return None

    async def _connect_one(self, config: dict[str, Any]) -> None:
        name = config.get("name", "unknown")
        transport = config.get("transport", "stdio")

        # Store config for reconnection
        self._configs[name] = config

        # Each server gets its own exit stack
        exit_stack = AsyncExitStack()
        self._exit_stacks[name] = exit_stack

        try:
            if transport == "stdio":
                session = await self._connect_stdio(config, exit_stack)
            elif transport in ("http", "streamable-http"):
                session = await self._connect_http(config, exit_stack)
            else:
                await exit_stack.aclose()
                raise ValueError(f"Unsupported MCP transport: {transport}")
        except BaseException:
            # Clean up on failure
            self._exit_stacks.pop(name, None)
            try:
                await exit_stack.aclose()
            except BaseException:
                pass
            raise

        self._sessions[name] = session

        # Discover and register tools
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            adapted = MCPToolAdapter(session, name, tool, manager=self)
            self._registry.register(adapted)

    async def _connect_stdio(
        self, config: dict[str, Any], exit_stack: AsyncExitStack,
    ) -> ClientSession:
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

        read_stream, write_stream = await exit_stack.enter_async_context(
            stdio_client(params)
        )
        session = await exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        return session

    async def _connect_http(
        self, config: dict[str, Any], exit_stack: AsyncExitStack,
    ) -> ClientSession:
        url = config["url"]
        name = config.get("name", "unknown")
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

        # Set up OAuth for browser-based authentication
        redirect_uri = f"http://127.0.0.1:{CALLBACK_PORT}/callback"
        storage = FileTokenStorage(name)
        oauth_auth = OAuthClientProvider(
            server_url=url,
            client_metadata=OAuthClientMetadata(
                client_name=f"agent-{name}",
                redirect_uris=[AnyUrl(redirect_uri)],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                token_endpoint_auth_method="client_secret_basic",
            ),
            storage=storage,
            redirect_handler=open_browser_redirect,
            callback_handler=wait_for_callback,
        )

        http_client = httpx.AsyncClient(
            headers=resolved_headers if resolved_headers else None,
            auth=oauth_auth,
        )

        read_stream, write_stream, _ = await exit_stack.enter_async_context(
            streamable_http_client(url, http_client=http_client)
        )
        session = await exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        return session

    async def _close_server(self, name: str) -> None:
        """Close a single server's connection."""
        self._sessions.pop(name, None)
        exit_stack = self._exit_stacks.pop(name, None)
        if exit_stack:
            try:
                await exit_stack.aclose()
            except BaseException:
                pass

        # Unregister all tools from this server
        prefix = f"mcp__{name}__"
        to_remove = [n for n in self._registry.list_names() if n.startswith(prefix)]
        for tool_name in to_remove:
            self._registry.unregister(tool_name)

    async def close(self) -> None:
        """Close all MCP connections gracefully."""
        for name in list(self._sessions.keys()):
            await self._close_server(name)
