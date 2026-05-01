"""Conversation state management."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.core.message import Message

logger = logging.getLogger(__name__)


@dataclass
class Conversation:
    """Holds the message list and tracks token usage."""
    messages: list[Message] = field(default_factory=list)
    system_prompt: str = ""
    total_tokens: int = 0
    on_append: Callable[[Message], None] | None = None

    def append(self, message: Message) -> None:
        self.messages.append(message)
        self.total_tokens += message.token_count
        if self.on_append is not None:
            try:
                self.on_append(message)
            except Exception as e:
                logger.debug("Conversation.on_append failed: %s", e)

    def to_api_messages(self) -> list[dict[str, Any]]:
        """Convert messages to the format expected by LLM APIs."""
        return [msg.to_dict() for msg in self.messages]

    def clear(self) -> None:
        self.messages.clear()
        self.total_tokens = 0

    def load_messages(self, messages: list[Message]) -> None:
        """Replace current messages with loaded ones, recalculating token count."""
        self.messages = sanitize_tool_pairs(list(messages))
        self.total_tokens = sum(m.token_count for m in self.messages)


def sanitize_tool_pairs(messages: list[Message]) -> list[Message]:
    """Fix orphaned tool_result blocks that have no matching tool_use.

    After compaction or a crash, a user message may contain tool_result
    blocks whose corresponding assistant tool_use was summarized away.
    The Anthropic API rejects these.  Convert orphaned tool_result
    messages to plain text so the conversation stays valid.
    """
    result: list[Message] = []
    for msg in messages:
        if msg.role != "user" or not _has_tool_results(msg):
            result.append(msg)
            continue

        # Collect tool_use IDs from the immediately preceding assistant message
        prev_tool_ids: set[str] = set()
        if result:
            prev = result[-1]
            if prev.role == "assistant":
                for block in prev.content:
                    if block.get("type") == "tool_use":
                        prev_tool_ids.add(block["id"])

        # Check if every tool_result has a matching tool_use
        orphaned = False
        for block in msg.content:
            if block.get("type") == "tool_result":
                if block.get("tool_use_id") not in prev_tool_ids:
                    orphaned = True
                    break

        if not orphaned:
            result.append(msg)
        else:
            # Convert to plain text, preserving the content for context
            text_parts = []
            for block in msg.content:
                if block.get("type") == "tool_result":
                    preview = str(block.get("content", ""))[:500]
                    text_parts.append(f"[Tool result]: {preview}")
                elif block.get("type") == "text":
                    text_parts.append(block["text"])
            if text_parts:
                replacement = Message.user("\n".join(text_parts))
                replacement.token_count = msg.token_count
                result.append(replacement)
            # else: drop empty message entirely

    return result


def _has_tool_results(msg: Message) -> bool:
    return any(b.get("type") == "tool_result" for b in msg.content)
