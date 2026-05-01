"""Integration test fixtures: mock LLM provider, CLI, and full agent wiring."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.config import Config
from agent.core.loop import AgentLoop
from agent.core.message import Message
from agent.history.storage import HistoryStorage
from agent.llm.base import (
    LLMProvider,
    ResponseComplete,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolUseEvent,
    UsageInfo,
)
from agent.memory.manager import MemoryManager
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Fake LLM provider that yields pre-configured responses
# ---------------------------------------------------------------------------

class FakeLLMProvider:
    """A controllable LLM provider for integration tests.

    Set ``self.responses`` to a list of response sequences. Each call to
    ``stream()`` pops the first entry and yields those events.

    Each response is a list of StreamEvent objects.
    """

    def __init__(self) -> None:
        self.responses: list[list[StreamEvent]] = []
        self.calls: list[dict[str, Any]] = []
        self._model = "test-model"

    def set_text_response(self, text: str, input_tokens: int = 100, output_tokens: int = 50) -> None:
        """Convenience: queue a simple text-only response."""
        self.responses.append([
            TextDelta(text=text),
            ResponseComplete(
                usage=UsageInfo(input_tokens=input_tokens, output_tokens=output_tokens),
                stop_reason="end_turn",
            ),
        ])

    def set_tool_then_text(
        self,
        tool_name: str,
        tool_input: dict,
        tool_id: str = "tool_001",
        final_text: str = "Done.",
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        """Queue a tool-use response followed by a text-only response."""
        # First LLM call: returns tool_use
        self.responses.append([
            ToolUseEvent(id=tool_id, name=tool_name, input=tool_input),
            ResponseComplete(
                usage=UsageInfo(input_tokens=input_tokens, output_tokens=output_tokens),
                stop_reason="tool_use",
            ),
        ])
        # Second LLM call: returns text after seeing tool result
        self.responses.append([
            TextDelta(text=final_text),
            ResponseComplete(
                usage=UsageInfo(input_tokens=input_tokens, output_tokens=output_tokens),
                stop_reason="end_turn",
            ),
        ])

    def set_multi_tool_response(
        self,
        tools: list[tuple[str, str, dict]],
        final_text: str = "Done.",
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        """Queue a response with multiple concurrent tool calls, then a text response.

        Args:
            tools: List of (tool_id, tool_name, tool_input) tuples.
        """
        events: list[StreamEvent] = [
            ToolUseEvent(id=tid, name=name, input=inp)
            for tid, name, inp in tools
        ]
        events.append(ResponseComplete(
            usage=UsageInfo(input_tokens=input_tokens, output_tokens=output_tokens),
            stop_reason="tool_use",
        ))
        self.responses.append(events)
        self.set_text_response(final_text, input_tokens, output_tokens)

    def set_thinking_then_text(
        self,
        thinking: str,
        text: str,
        thinking_blocks: list[dict] | None = None,
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        """Queue a response with thinking deltas followed by text."""
        self.responses.append([
            ThinkingDelta(text=thinking),
            TextDelta(text=text),
            ResponseComplete(
                usage=UsageInfo(input_tokens=input_tokens, output_tokens=output_tokens),
                stop_reason="end_turn",
                thinking_blocks=thinking_blocks or [
                    {"type": "thinking", "thinking": thinking, "signature": "sig_test"}
                ],
            ),
        ])

    def set_error_response(self, error: Exception) -> None:
        """Queue a response that raises an exception mid-stream."""
        self.responses.append([_ErrorSentinel(error)])

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
        reasoning: Any = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.calls.append({
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        })
        if not self.responses:
            # Default: empty text response
            yield TextDelta(text="(no response configured)")
            yield ResponseComplete(
                usage=UsageInfo(input_tokens=10, output_tokens=5),
                stop_reason="end_turn",
            )
            return
        events = self.responses.pop(0)
        for event in events:
            if isinstance(event, _ErrorSentinel):
                raise event.error
            yield event


class _ErrorSentinel:
    """Internal marker to trigger an exception during streaming."""
    def __init__(self, error: Exception) -> None:
        self.error = error


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()


# ---------------------------------------------------------------------------
# Mock CLI that captures output without terminal I/O
# ---------------------------------------------------------------------------

class FakeCLI:
    """Captures CLI output for assertions, no real terminal I/O."""

    def __init__(self) -> None:
        self.output: list[str] = []
        self.tool_uses: list[tuple[str, dict]] = []
        self.tool_results: list[tuple[str, str, bool]] = []
        self.thinking_started: int = 0
        self.thinking_ended: int = 0

    def print_welcome(self, provider: str, model: str) -> None:
        self.output.append(f"Welcome: {provider}/{model}")

    def print_info(self, text: str) -> None:
        self.output.append(text)

    def print_error(self, text: str) -> None:
        self.output.append(f"ERROR: {text}")

    def print_text_delta(self, text: str) -> None:
        self.output.append(text)

    def print_thinking_delta(self, text: str) -> None:
        self.output.append(f"[thinking] {text}")

    def print_assistant_text(self, text: str) -> None:
        self.output.append(text)

    def print_tool_use(self, name: str, input_data: dict) -> None:
        self.tool_uses.append((name, input_data))

    def print_tool_result(self, name: str, result: str, is_error: bool) -> None:
        self.tool_results.append((name, result, is_error))

    def print_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.output.append(f"Tokens: {input_tokens}in/{output_tokens}out")

    def print_compaction_notice(self) -> None:
        self.output.append("[compaction]")

    def start_response(self) -> None:
        pass

    def end_response(self) -> None:
        pass

    def start_thinking(self) -> None:
        self.thinking_started += 1

    def end_thinking(self) -> None:
        self.thinking_ended += 1

    async def get_input(self) -> str | None:
        return None


@pytest.fixture
def fake_cli() -> FakeCLI:
    return FakeCLI()


# ---------------------------------------------------------------------------
# Wired-up components
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_manager(test_config: Config, tmp_path) -> MemoryManager:
    return MemoryManager(
        config=test_config.memory,
        base_dir=tmp_path,
        mem0_client=None,
    )


@pytest.fixture
def history_storage(test_config: Config, tmp_path) -> HistoryStorage:
    return HistoryStorage(test_config.history.dir, tmp_path)


@pytest.fixture
def tool_registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def tool_executor(tool_registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(tool_registry)


# ---------------------------------------------------------------------------
# Agent builder fixture
# ---------------------------------------------------------------------------

def build_agent(
    fake_llm,
    fake_cli,
    test_config,
    tmp_path,
    extra_tools=None,
    memory_manager=None,
    history=None,
    skill_loader=None,
    skills=None,
) -> AgentLoop:
    """Build an AgentLoop wired with fakes for testing."""
    registry = ToolRegistry()
    if extra_tools:
        for t in extra_tools:
            registry.register(t)
    executor = ToolExecutor(registry)
    return AgentLoop(
        config=test_config,
        llm=fake_llm,
        cli=fake_cli,
        project_dir=tmp_path,
        tool_registry=registry,
        tool_executor=executor,
        memory_manager=memory_manager,
        history=history,
        skill_loader=skill_loader,
        skills=skills,
    )
