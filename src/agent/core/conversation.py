"""Conversation state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.core.message import Message


@dataclass
class Conversation:
    """Holds the message list and tracks token usage."""
    messages: list[Message] = field(default_factory=list)
    system_prompt: str = ""
    total_tokens: int = 0

    def append(self, message: Message) -> None:
        self.messages.append(message)
        self.total_tokens += message.token_count

    def to_api_messages(self) -> list[dict[str, Any]]:
        """Convert messages to the format expected by LLM APIs."""
        return [msg.to_dict() for msg in self.messages]

    def clear(self) -> None:
        self.messages.clear()
        self.total_tokens = 0
