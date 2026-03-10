"""Adapts MCP tools to the internal Tool protocol."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp import ClientSession

if TYPE_CHECKING:
    from agent.tools.mcp.client import MCPManager

logger = logging.getLogger(__name__)


class MCPToolAdapter:
    """Wraps an MCP server tool as an internal Tool with automatic reconnection."""

    def __init__(
        self,
        session: ClientSession,
        server_name: str,
        mcp_tool: Any,
        manager: MCPManager | None = None,
    ) -> None:
        self._session = session
        self._server_name = server_name
        self._mcp_tool = mcp_tool
        self._manager = manager

    @property
    def name(self) -> str:
        return f"mcp__{self._server_name}__{self._mcp_tool.name}"

    @property
    def description(self) -> str:
        return self._mcp_tool.description or ""

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._mcp_tool.inputSchema or {"type": "object", "properties": {}}

    async def execute(self, **params: Any) -> str:
        try:
            return await self._call(params)
        except BaseException as first_error:
            # Connection dead — try to reconnect once
            if self._manager is None:
                raise RuntimeError(
                    f"MCP tool '{self._mcp_tool.name}' on server "
                    f"'{self._server_name}' failed: {first_error}"
                ) from first_error

            logger.info(
                "MCP tool '%s' failed (%s), attempting reconnect to '%s'",
                self._mcp_tool.name, first_error, self._server_name,
            )
            new_session = await self._manager.reconnect(self._server_name)
            if new_session is None:
                raise RuntimeError(
                    f"MCP tool '{self._mcp_tool.name}' on server "
                    f"'{self._server_name}' failed and reconnection failed: {first_error}"
                ) from first_error

            # Update our session reference and retry
            self._session = new_session
            try:
                return await self._call(params)
            except BaseException as retry_error:
                raise RuntimeError(
                    f"MCP tool '{self._mcp_tool.name}' on server "
                    f"'{self._server_name}' failed after reconnect: {retry_error}"
                ) from retry_error

    async def _call(self, params: dict[str, Any]) -> str:
        result = await self._session.call_tool(self._mcp_tool.name, params)
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts) or "(no output)"
