"""Conversation compaction: flush to memory, summarize old messages."""

from __future__ import annotations

import json
from typing import Any

from agent.config import CompactionConfig
from agent.core.conversation import Conversation
from agent.core.message import Message
from agent.core.tokens import count_message_tokens, count_tokens
from agent.llm.base import LLMProvider, TextDelta
from agent.memory.manager import MemoryManager

# Maximum tokens allowed for a single tool_result content block after compaction.
# Larger results get truncated to a preview to keep the context window manageable.
_MAX_TOOL_RESULT_TOKENS = 800


EXTRACT_PROMPT = """\
Analyze this conversation and extract the most important information that should be \
remembered for future conversations. Include:
- Key decisions made
- Important facts about the project or codebase
- User preferences discovered
- Problems solved and their solutions
- File paths and code patterns mentioned

Format as concise markdown bullet points. Only include genuinely important information."""

SUMMARIZE_PROMPT = """\
Summarize this conversation concisely. Preserve:
- What tasks were performed
- Key decisions and their rationale
- File paths modified
- Any unresolved items or next steps

Be brief but complete. Format as markdown."""


class Compactor:
    """Handles conversation compaction when token limits approach."""

    def __init__(
        self,
        config: CompactionConfig,
        llm: LLMProvider,
        memory_manager: MemoryManager | None,
        conversation: Conversation,
    ) -> None:
        self._config = config
        self._llm = llm
        self._memory = memory_manager
        self._conversation = conversation

    async def maybe_compact(self, force: bool = False) -> bool:
        """Check threshold and compact if needed. Returns True if compacted."""
        if not force and self._conversation.total_tokens < self._config.threshold_tokens:
            return False

        await self._flush_to_memory()
        await self._summarize_old_messages()
        return True

    async def _flush_to_memory(self) -> None:
        """Ask LLM to extract key info, write to memory."""
        if not self._memory:
            return

        # Build a condensed version of the conversation for extraction
        conversation_text = self._format_conversation(self._conversation.messages)
        extract_messages = [{"role": "user", "content": f"{EXTRACT_PROMPT}\n\n{conversation_text}"}]

        extracted = await self._call_llm_simple(extract_messages)
        if extracted:
            await self._memory.save_daily(f"Compaction extracted:\n{extracted}")

    async def _summarize_old_messages(self) -> None:
        """Keep recent messages, summarize older ones."""
        keep = self._config.keep_recent_messages
        messages = self._conversation.messages

        if len(messages) <= keep:
            return

        split = len(messages) - keep

        # Adjust split point so we don't separate tool_use/tool_result pairs.
        # If the first recent message has tool_result blocks, its preceding
        # assistant message (with tool_use) was split into old_messages,
        # causing an orphaned tool_result. Move split back to keep the pair.
        while split > 0 and self._has_tool_result(messages[split]):
            split -= 1

        if split <= 0:
            return

        old_messages = messages[:split]
        recent_messages = messages[split:]

        conversation_text = self._format_conversation(old_messages)
        summarize_messages = [{"role": "user", "content": f"{SUMMARIZE_PROMPT}\n\n{conversation_text}"}]

        summary = await self._call_llm_simple(summarize_messages)
        if not summary:
            summary = "(Conversation history was compacted)"

        summary_msg = Message.user(f"[Previous conversation summary]\n{summary}")
        summary_msg.token_count = count_message_tokens(summary_msg.to_dict())

        # Truncate oversized tool results in recent messages so they don't
        # dominate the context window after compaction.
        recent_messages = [self._truncate_tool_results(m) for m in recent_messages]

        self._conversation.messages = [summary_msg] + recent_messages
        self._conversation.total_tokens = sum(m.token_count for m in self._conversation.messages)

    async def _call_llm_simple(self, messages: list[dict[str, Any]]) -> str:
        """Make a simple LLM call (no tools) and return text."""
        parts: list[str] = []
        async for event in self._llm.stream(
            system="You are a helpful assistant that extracts and summarizes information.",
            messages=messages,
            max_tokens=2048,
        ):
            if isinstance(event, TextDelta):
                parts.append(event.text)
        return "".join(parts)

    @staticmethod
    def _has_tool_result(message: Message) -> bool:
        """Check if a message contains tool_result blocks."""
        return any(block.get("type") == "tool_result" for block in message.content)

    @staticmethod
    def _truncate_tool_results(message: Message) -> Message:
        """Shrink oversized tool_result content blocks in a message.

        After compaction, large tool results (e.g. Glean search responses,
        file reads) can consume most of the remaining context.  This replaces
        tool_result content that exceeds *_MAX_TOOL_RESULT_TOKENS* with a
        truncated preview, keeping the conversation within budget.
        """
        if message.role != "user":
            return message

        changed = False
        new_content: list[dict[str, Any]] = []
        for block in message.content:
            if block.get("type") == "tool_result":
                raw = block.get("content", "")
                content_str = raw if isinstance(raw, str) else json.dumps(raw)
                tokens = count_tokens(content_str)
                if tokens > _MAX_TOOL_RESULT_TOKENS:
                    # Keep a useful preview: first ~2000 chars typically ≈ 500-700 tokens
                    truncated = content_str[:3000]
                    new_block = dict(block)
                    new_block["content"] = f"{truncated}\n\n... [truncated from {tokens} tokens during compaction]"
                    new_content.append(new_block)
                    changed = True
                else:
                    new_content.append(block)
            else:
                new_content.append(block)

        if not changed:
            return message

        new_msg = Message(role=message.role, content=new_content)
        new_msg.token_count = count_message_tokens(new_msg.to_dict())
        return new_msg

    def _format_conversation(self, messages: list[Message]) -> str:
        """Format messages into readable text for summarization."""
        parts = []
        for msg in messages:
            role = msg.role.upper()
            text = msg.text
            if text:
                parts.append(f"[{role}]: {text}")
            else:
                # Tool interactions
                for block in msg.content:
                    if block.get("type") == "tool_use":
                        parts.append(f"[{role}]: Called tool '{block['name']}'")
                    elif block.get("type") == "tool_result":
                        preview = str(block.get("content", ""))[:200]
                        parts.append(f"[TOOL RESULT]: {preview}")
        return "\n\n".join(parts)
