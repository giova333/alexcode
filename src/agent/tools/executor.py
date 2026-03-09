"""Tool call dispatcher."""

from __future__ import annotations

from typing import Any

from agent.tools.base import ToolError
from agent.tools.registry import ToolRegistry


class ToolExecutor:
    """Looks up and executes tools from the registry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        tool = self._registry.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool: {name}")
        return await tool.execute(**params)
