"""Memory tools: search, save, and read from the agent's persistent memory."""

from __future__ import annotations

import json
from typing import Any

from agent.memory.manager import MemoryManager


class MemorySearchTool:
    """Search across mem0 memories (project, plus global if enabled)."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search the agent's persistent mem0 memory (scope is configured via "
            "memory.scope: 'global' for cross-project, 'project' for this project only). "
            "Use this to recall facts, decisions, or context from prior turns and prior "
            "sessions. Each result is tagged with source matching the configured scope."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query — can be a question, keywords, or a topic.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **params: Any) -> str:
        query = params["query"]
        top_k = params.get("top_k", 5)
        results = await self._memory.search(query, top_k=top_k)
        if not results:
            return "No matching memories found."
        return json.dumps(results, indent=2)


class MemorySaveTool:
    """Append a curated entry to MEMORY.md (stable, long-term knowledge)."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    @property
    def name(self) -> str:
        return "memory_save"

    @property
    def description(self) -> str:
        return (
            "Append an entry to MEMORY.md — the human-curated long-term knowledge file "
            "(project conventions, user preferences, architecture decisions, durable "
            "facts that should persist across sessions). Conversation messages are "
            "captured automatically by mem0; use this tool only when something is "
            "worth promoting to the curated file."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The entry to append. Use concise markdown.",
                },
            },
            "required": ["content"],
        }

    async def execute(self, **params: Any) -> str:
        return await self._memory.save_main(params["content"])
