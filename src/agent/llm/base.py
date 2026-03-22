"""LLM provider protocol and stream event types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from agent.config import ReasoningConfig


@dataclass
class TextDelta:
    """A chunk of streamed text."""
    text: str


@dataclass
class ThinkingDelta:
    """A chunk of streamed thinking/reasoning text."""
    text: str


@dataclass
class ToolUseEvent:
    """The LLM wants to call a tool."""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class UsageInfo:
    """Token usage from the API response."""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ResponseComplete:
    """Signals end of response with usage info."""
    usage: UsageInfo = field(default_factory=UsageInfo)
    stop_reason: str = ""
    thinking_blocks: list[dict[str, Any]] = field(default_factory=list)


# Union of all stream events
StreamEvent = TextDelta | ThinkingDelta | ToolUseEvent | ResponseComplete


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
        reasoning: ReasoningConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a response from the LLM.

        Yields StreamEvent instances: TextDelta, ThinkingDelta, ToolUseEvent, ResponseComplete.
        """
        ...
