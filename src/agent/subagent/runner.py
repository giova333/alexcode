"""Lightweight agent loop for subagent task execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent.compaction.compactor import Compactor
from agent.config import Config
from agent.core.conversation import Conversation
from agent.core.message import Message
from agent.core.tokens import count_message_tokens
from agent.llm.base import LLMProvider, TextDelta, ThinkingDelta, ToolUseEvent, ResponseComplete
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agent.cli import CLI

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 50


class SubagentRunner:
    """Runs a single task to completion using an ephemeral conversation.

    This is a stripped-down version of AgentLoop._run_llm_cycle() with no CLI
    interaction, no history persistence, no plan mode, and no memory writes.

    When *cli* is provided, streaming output (text deltas, tool events) is
    displayed in the terminal in real time — the same way AgentLoop does it.
    """

    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        config: Config,
        system_prompt: str,
        cli: CLI | None = None,
    ) -> None:
        self._llm = llm
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._config = config
        self._system_prompt = system_prompt
        self._cli = cli
        self._conversation = Conversation()
        self._compactor = Compactor(
            config.compaction,
            llm,
            memory_manager=None,
            conversation=self._conversation,
        )

    async def run(self, task: str) -> str:
        """Execute the task and return the final text response."""
        user_msg = Message.user(task)
        user_msg.token_count = count_message_tokens(user_msg.to_dict())
        self._conversation.append(user_msg)

        return await self._run_llm_cycle()

    async def _run_llm_cycle(self) -> str:
        """Call LLM, handle tool use, repeat until text response."""
        tools = self._tool_registry.all_definitions()

        for _ in range(_MAX_ITERATIONS):
            text_parts: list[str] = []
            tool_uses: list[ToolUseEvent] = []
            usage_info: ResponseComplete | None = None
            thinking_blocks: list[dict[str, Any]] = []
            is_thinking = False

            reasoning_cfg = (
                self._config.reasoning if self._config.reasoning.enabled else None
            )

            if self._cli:
                self._cli.start_response()

            async for event in self._llm.stream(
                system=self._system_prompt,
                messages=self._conversation.to_api_messages(),
                tools=tools if tools else None,
                max_tokens=self._config.max_tokens,
                reasoning=reasoning_cfg,
            ):
                if isinstance(event, ThinkingDelta):
                    if self._cli:
                        if not is_thinking:
                            is_thinking = True
                            self._cli.start_thinking()
                        if self._config.reasoning.show_thinking:
                            self._cli.print_thinking_delta(event.text)
                elif isinstance(event, TextDelta):
                    if self._cli and is_thinking:
                        is_thinking = False
                        self._cli.end_thinking()
                    text_parts.append(event.text)
                    if self._cli:
                        self._cli.print_text_delta(event.text)
                elif isinstance(event, ToolUseEvent):
                    if self._cli and is_thinking:
                        is_thinking = False
                        self._cli.end_thinking()
                    tool_uses.append(event)
                elif isinstance(event, ResponseComplete):
                    if self._cli and is_thinking:
                        is_thinking = False
                        self._cli.end_thinking()
                    usage_info = event

            if self._cli:
                self._cli.end_response()

            # Build assistant message
            content_blocks: list[dict[str, Any]] = []
            if usage_info and usage_info.thinking_blocks:
                content_blocks.extend(usage_info.thinking_blocks)
            full_text = "".join(text_parts)
            if full_text:
                content_blocks.append({"type": "text", "text": full_text})
            for tu in tool_uses:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tu.id,
                    "name": tu.name,
                    "input": tu.input,
                })

            if content_blocks:
                assistant_msg = Message(role="assistant", content=content_blocks)
                assistant_msg.token_count = count_message_tokens(assistant_msg.to_dict())
                self._conversation.append(assistant_msg)

            if usage_info:
                self._conversation.total_tokens = usage_info.usage.input_tokens
                if self._cli:
                    self._cli.print_usage(usage_info.usage.input_tokens, usage_info.usage.output_tokens)

            # No tool calls — we have the final response
            if not tool_uses:
                return full_text

            # Execute tools
            tool_result_blocks: list[dict[str, Any]] = []
            for tu in tool_uses:
                try:
                    if self._cli:
                        self._cli.print_tool_use(tu.name, tu.input)
                    result_text = await self._tool_executor.execute(tu.name, tu.input)
                    is_error = False
                    if self._cli:
                        self._cli.print_tool_result(tu.name, result_text, is_error)
                except Exception as e:
                    result_text = f"Error executing {tu.name}: {e}"
                    is_error = True
                    if self._cli:
                        self._cli.print_tool_result(tu.name, result_text, is_error)
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                    "is_error": is_error,
                })

            result_msg = Message(role="user", content=tool_result_blocks)
            result_msg.token_count = count_message_tokens(result_msg.to_dict())
            self._conversation.append(result_msg)

            # Compact if needed
            await self._compactor.maybe_compact()

        return "Subagent reached maximum iterations without completing the task."
