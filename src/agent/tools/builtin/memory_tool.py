"""Memory tools: search, save, and read from the agent's persistent memory."""

from __future__ import annotations

import json
from typing import Any

from agent.memory.manager import MemoryManager


class MemorySearchTool:
    """Search across all memory: MEMORY.md, topics, daily notes, and conversation history."""

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
            "session, find a decision that was made earlier, or look up project-specific knowledge "
            "that was previously learned."
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
            "Save important information to persistent memory so it can be recalled in future "
            "conversations. Use this to remember: key decisions, user preferences, project "
            "conventions, solutions to problems, important file paths, or anything the user "
            "asks you to remember. Optionally specify a topic to organize by subject."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to save. Use concise markdown bullet points.",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic name to organize the memory (e.g., 'debugging', 'architecture', 'preferences'). If omitted, saves to main memory.",
                },
            },
            "required": ["content"],
        }

    async def execute(self, **params: Any) -> str:
        content = params["content"]
        topic = params.get("topic")
        result = await self._memory.save(content, topic=topic)
        return result


class MemoryReadTool:
    """Read specific memory files and topics."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager

    @property
    def name(self) -> str:
        return "memory_read"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a specific memory file. Can read the main MEMORY.md, "
            "a topic file, or daily notes for a specific date. Use this after memory_search "
            "identifies a relevant source, or to check what's already stored."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "What to read: 'main' for MEMORY.md, 'topics' to list all topics, or a topic name to read that topic file.",
                    "default": "main",
                },
                "date": {
                    "type": "string",
                    "description": "For daily notes: ISO date string (YYYY-MM-DD). If provided, reads that day's notes.",
                },
            },
        }

    async def execute(self, **params: Any) -> str:
        target = params.get("target", "main")
        date_str = params.get("date")

        if date_str:
            content = await self._memory.read_daily(date_str)
            return content if content else f"No daily notes for {date_str}."

        if target == "main":
            content = await self._memory.read_main()
            return content if content else "Main memory is empty."

        if target == "topics":
            topics = await self._memory.list_topics()
            if not topics:
                return "No topic files found."
            return "Available topics:\n" + "\n".join(f"- {t}" for t in topics)

        # Read specific topic
        content = await self._memory.read_topic(target)
        return content if content else f"Topic '{target}' not found."
