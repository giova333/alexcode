"""OpenAI LLM provider with API key and OAuth support."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI

from agent.config import OpenAIConfig, ReasoningConfig
from agent.llm.base import (
    ResponseComplete,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolUseEvent,
    UsageInfo,
)


class OAuthTokenManager:
    """Manages OAuth2 client_credentials tokens with caching and auto-refresh."""

    def __init__(self, client_id: str, client_secret: str, token_url: str, scope: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._scope = scope
        self._token: str | None = None
        self._expires_at: float = 0

    async def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": self._scope,
                },
            )
            response.raise_for_status()
            data = response.json()

        self._token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        return self._token


class OpenAIProvider:
    """Wraps the OpenAI SDK for streaming chat with tool use."""

    def __init__(self, config: OpenAIConfig, model: str) -> None:
        self._model = model
        self._config = config
        self._oauth: OAuthTokenManager | None = None

        if config.auth == "oauth" and config.oauth.token_url:
            self._oauth = OAuthTokenManager(
                client_id=config.oauth.client_id,
                client_secret=config.oauth.client_secret,
                token_url=config.oauth.token_url,
                scope=config.oauth.scope,
            )

    async def _get_client(self) -> AsyncOpenAI:
        kwargs: dict[str, Any] = {}
        if self._config.base_url:
            kwargs["base_url"] = self._config.base_url

        if self._oauth:
            token = await self._oauth.get_token()
            kwargs["api_key"] = token
        elif self._config.api_key:
            kwargs["api_key"] = self._config.api_key

        return AsyncOpenAI(**kwargs)

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic-style tool defs to OpenAI function calling format."""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return openai_tools

    def _convert_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic-style messages to OpenAI format."""
        result = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", [])

            if isinstance(content, str):
                result.append({"role": role, "content": content})
                continue

            # Handle content blocks
            text_parts = []
            tool_calls = []
            tool_results = []

            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block["text"])
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
                elif btype == "tool_result":
                    tool_results.append(block)

            if tool_calls:
                msg_dict: dict[str, Any] = {"role": "assistant"}
                if text_parts:
                    msg_dict["content"] = "\n".join(text_parts)
                msg_dict["tool_calls"] = tool_calls
                result.append(msg_dict)
            elif tool_results:
                for tr in tool_results:
                    result.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": tr.get("content", ""),
                    })
            elif text_parts:
                result.append({"role": role, "content": "\n".join(text_parts)})

        return result

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
        reasoning: ReasoningConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        client = await self._get_client()

        openai_messages = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        openai_messages.extend(self._convert_messages(messages))

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        # OpenAI reasoning (o1/o3 models)
        if reasoning and reasoning.enabled:
            effort = reasoning.effort if reasoning.effort in ("low", "medium", "high") else "medium"
            kwargs["reasoning_effort"] = effort

        # Track tool calls being built across chunks
        tool_call_buffers: dict[int, dict] = {}
        usage = UsageInfo()

        stream_resp = await client.chat.completions.create(**kwargs)

        async for chunk in stream_resp:
            if chunk.usage:
                usage = UsageInfo(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                yield TextDelta(text=delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_call_buffers:
                        tool_call_buffers[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    buf = tool_call_buffers[idx]
                    if tc.id:
                        buf["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            buf["name"] = tc.function.name
                        if tc.function.arguments:
                            buf["arguments"] += tc.function.arguments

            if chunk.choices[0].finish_reason:
                # Emit any accumulated tool calls
                for buf in tool_call_buffers.values():
                    try:
                        input_data = json.loads(buf["arguments"]) if buf["arguments"] else {}
                    except json.JSONDecodeError:
                        input_data = {}
                    yield ToolUseEvent(
                        id=buf["id"],
                        name=buf["name"],
                        input=input_data,
                    )
                tool_call_buffers.clear()

        yield ResponseComplete(usage=usage, stop_reason="stop")
