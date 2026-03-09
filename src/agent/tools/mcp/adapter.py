"""Adapts MCP tools to the internal Tool protocol."""

from __future__ import annotations

from typing import Any

from mcp import ClientSession


class MCPToolAdapter:
    """Wraps an MCP server tool as an internal Tool."""

    def __init__(self, session: ClientSession, server_name: str, mcp_tool: Any) -> None:
        self._session = session
        self._server_name = server_name
        self._mcp_tool = mcp_tool

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
        result = await self._session.call_tool(self._mcp_tool.name, params)
        # Extract text from result content
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts) or "(no output)"
