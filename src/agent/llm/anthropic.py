"""Anthropic Claude LLM provider."""

from __future__ import annotations

from typing import Any, AsyncIterator

import anthropic

from agent.config import AnthropicConfig
from agent.llm.base import (
    ResponseComplete,
    StreamEvent,
    TextDelta,
    ToolUseEvent,
    UsageInfo,
)


class AnthropicProvider:
    """Wraps the Anthropic SDK for streaming chat with tool use."""

    def __init__(self, config: AnthropicConfig, model: str) -> None:
        self._model = model
        kwargs: dict[str, Any] = {}
        if config.api_key:
            kwargs["api_key"] = config.api_key
        self._client = anthropic.AsyncAnthropic(**kwargs)

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamEvent]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            current_tool_id = ""
            current_tool_name = ""
            tool_input_json = ""

            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_id = block.id
                        current_tool_name = block.name
                        tool_input_json = ""

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield TextDelta(text=delta.text)
                    elif delta.type == "input_json_delta":
                        tool_input_json += delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_name:
                        import json
                        try:
                            input_data = json.loads(tool_input_json) if tool_input_json else {}
                        except json.JSONDecodeError:
                            input_data = {}
                        yield ToolUseEvent(
                            id=current_tool_id,
                            name=current_tool_name,
                            input=input_data,
                        )
                        current_tool_id = ""
                        current_tool_name = ""
                        tool_input_json = ""

                elif event.type == "message_stop":
                    pass

            # Get final message for usage
            final = await stream.get_final_message()
            yield ResponseComplete(
                usage=UsageInfo(
                    input_tokens=final.usage.input_tokens,
                    output_tokens=final.usage.output_tokens,
                ),
                stop_reason=final.stop_reason or "",
            )
