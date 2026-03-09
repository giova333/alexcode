"""Tool protocol definition."""

from __future__ import annotations

from typing import Any, Protocol


class Tool(Protocol):
    """Every tool (built-in, MCP, skill) implements this protocol."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    async def execute(self, **params: Any) -> str: ...


class ToolError(Exception):
    """Raised when a tool execution fails."""
