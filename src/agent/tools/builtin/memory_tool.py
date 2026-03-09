"""Memory tools: search, save, and read from the agent's persistent memory."""

from __future__ import annotations

import json
from typing import Any

from agent.memory.manager import MemoryManager


class MemorySearchTool:
    """Search across all memory: MEMORY.md, daily notes, and conversation history."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search the agent's persistent memory including past conversations, daily notes, "
            "and saved knowledge. Use this when you need to recall something from a previous "
            "session, find a decision that was made earlier, or look up project-specific knowledge."
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
    """Save information to persistent memory for future sessions."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    @property
    def name(self) -> str:
        return "memory_save"

    @property
    def description(self) -> str:
        return (
            "Save information to persistent memory. By default writes to today's daily notes. "
            "Use target='main' ONLY for stable, long-term knowledge that won't change "
            "(project conventions, user preferences, architecture decisions). "
            "Everything else — session notes, discoveries, decisions, activity — goes to daily."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to save. Use concise markdown.",
                },
                "target": {
                    "type": "string",
                    "enum": ["daily", "main"],
                    "description": "Where to save: 'daily' (default) for today's notes, 'main' for stable long-term MEMORY.md.",
                    "default": "daily",
                },
            },
            "required": ["content"],
        }

    async def execute(self, **params: Any) -> str:
        content = params["content"]
        target = params.get("target", "daily")
        if target == "main":
            return await self._memory.save_main(content)
        return await self._memory.save_daily(content)


class MemoryReadTool:
    """Read specific memory files."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    @property
    def name(self) -> str:
        return "memory_read"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a memory file. Can read MEMORY.md or daily notes "
            "for a specific date. Use after memory_search identifies a relevant source."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["main", "daily", "dates"],
                    "description": "What to read: 'main' for MEMORY.md, 'daily' for a day's notes, 'dates' to list available daily files.",
                    "default": "main",
                },
                "date": {
                    "type": "string",
                    "description": "For daily notes: ISO date string (YYYY-MM-DD). If omitted with target='daily', reads today's notes.",
                },
            },
        }

    async def execute(self, **params: Any) -> str:
        target = params.get("target", "main")
        date_str = params.get("date")

        if target == "dates":
            dates = await self._memory.list_daily_dates()
            if not dates:
                return "No daily note files found."
            return "Available dates:\n" + "\n".join(f"- {d}" for d in dates)

        if target == "daily":
            content = await self._memory.read_daily(date_str)
            label = date_str or "today"
            return content if content else f"No daily notes for {label}."

        # main
        content = await self._memory.read_main()
        return content if content else "MEMORY.md is empty."
