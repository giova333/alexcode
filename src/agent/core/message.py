"""Message data structures for the conversation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """A single message in the conversation.

    Content follows Anthropic's content block format:
    [{"type": "text", "text": "..."}, {"type": "tool_use", ...}, ...]
    """
    role: str  # "user", "assistant"
    content: list[dict[str, Any]] = field(default_factory=list)
    token_count: int = 0

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", content=[{"type": "text", "text": text}])

    @classmethod
    def assistant(cls, text: str) -> Message:
        return cls(role="assistant", content=[{"type": "text", "text": text}])

    @classmethod
    def tool_result(cls, tool_use_id: str, content: str, is_error: bool = False) -> Message:
        return cls(
            role="user",
            content=[{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
                "is_error": is_error,
            }],
        )

    @property
    def text(self) -> str:
        """Extract concatenated text from all text content blocks."""
        parts = []
        for block in self.content:
            if block.get("type") == "text":
                parts.append(block["text"])
        return "".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}
