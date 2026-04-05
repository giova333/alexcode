"""Central tool registry."""

from __future__ import annotations

from typing import Any

from agent.tools.base import Tool


class ToolRegistry:
    """Stores tools and generates API-compatible definitions."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def all_definitions(self) -> list[dict[str, Any]]:
        """Generate tool definitions in Anthropic API format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    def definitions_for(self, names: set[str]) -> list[dict[str, Any]]:
        """Generate tool definitions only for the given set of tool names."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
            if tool.name in names
        ]

    def clone_excluding(self, exclude_names: set[str]) -> ToolRegistry:
        """Create a new registry with all tools except the excluded ones."""
        new_registry = ToolRegistry()
        for name, tool in self._tools.items():
            if name not in exclude_names:
                new_registry.register(tool)
        return new_registry

    def list_names(self) -> list[str]:
        return list(self._tools.keys())
