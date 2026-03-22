"""Integration tests for the compaction system."""

from __future__ import annotations

import pytest

from agent.compaction.compactor import Compactor, _MAX_TOOL_RESULT_TOKENS
from agent.config import CompactionConfig
from agent.core.conversation import Conversation
from agent.core.message import Message
from agent.core.tokens import count_tokens
from agent.llm.base import TextDelta, ResponseComplete, UsageInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conversation(messages: list[Message], total_tokens: int = 0) -> Conversation:
    conv = Conversation()
    for m in messages:
        conv.messages.append(m)
    conv.total_tokens = total_tokens
    return conv


def _user_msg(text: str, tokens: int = 50) -> Message:
    m = Message.user(text)
    m.token_count = tokens
    return m


def _assistant_msg(text: str, tokens: int = 50) -> Message:
    m = Message.assistant(text)
    m.token_count = tokens
    return m


def _tool_result_msg(tool_use_id: str, content: str, tokens: int = 50) -> Message:
    m = Message.tool_result(tool_use_id, content)
    m.token_count = tokens
    return m


def _tool_use_msg(tool_id: str, tool_name: str, tokens: int = 50) -> Message:
    m = Message(
        role="assistant",
        content=[{"type": "tool_use", "id": tool_id, "name": tool_name, "input": {}}],
    )
    m.token_count = tokens
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCompactionTrigger:
    """Compaction should only run when token threshold is exceeded."""

    async def test_no_compaction_below_threshold(self, fake_llm, memory_manager):
        config = CompactionConfig(threshold_tokens=1000, keep_recent_messages=4)
        conv = _make_conversation(
            [_user_msg("hi"), _assistant_msg("hello")],
            total_tokens=500,
        )
        compactor = Compactor(config, fake_llm, memory_manager, conv)

        result = await compactor.maybe_compact()
        assert result is False

    async def test_compaction_above_threshold(self, fake_llm, memory_manager):
        config = CompactionConfig(threshold_tokens=100, keep_recent_messages=2)
        msgs = [_user_msg(f"msg {i}", tokens=50) for i in range(10)]
        msgs += [_assistant_msg(f"reply {i}", tokens=50) for i in range(10)]
        conv = _make_conversation(msgs, total_tokens=1000)

        # Fake LLM needs to return text for extract + summarize calls
        fake_llm.set_text_response("extracted info")
        fake_llm.set_text_response("summary of conversation")

        compactor = Compactor(config, fake_llm, memory_manager, conv)
        result = await compactor.maybe_compact()

        assert result is True
        # Messages should be reduced
        assert len(conv.messages) < 20
        # Token count should be recalculated and reduced
        assert conv.total_tokens < 1000

    async def test_force_compaction(self, fake_llm, memory_manager):
        config = CompactionConfig(threshold_tokens=999999, keep_recent_messages=2)
        msgs = [_user_msg("a"), _assistant_msg("b"), _user_msg("c"), _assistant_msg("d")]
        conv = _make_conversation(msgs, total_tokens=10)

        fake_llm.set_text_response("extracted")
        fake_llm.set_text_response("summary")

        compactor = Compactor(config, fake_llm, memory_manager, conv)
        result = await compactor.maybe_compact(force=True)

        assert result is True


@pytest.mark.integration
class TestCompactionSummarization:
    """Old messages are replaced by a summary, recent messages kept."""

    async def test_keeps_recent_messages(self, fake_llm, memory_manager):
        config = CompactionConfig(threshold_tokens=100, keep_recent_messages=2)
        msgs = [
            _user_msg("old 1"), _assistant_msg("old reply 1"),
            _user_msg("old 2"), _assistant_msg("old reply 2"),
            _user_msg("recent 1"), _assistant_msg("recent reply 1"),
        ]
        conv = _make_conversation(msgs, total_tokens=1000)

        fake_llm.set_text_response("extracted facts")
        fake_llm.set_text_response("Conversation summary here")

        compactor = Compactor(config, fake_llm, memory_manager, conv)
        await compactor.maybe_compact()

        # First message should be the summary
        assert "[Previous conversation summary]" in conv.messages[0].text
        assert "Conversation summary here" in conv.messages[0].text
        # Recent messages preserved
        assert conv.messages[-1].text == "recent reply 1"

    async def test_tool_pair_not_split(self, fake_llm, memory_manager):
        """Compaction should not separate tool_use from its tool_result."""
        config = CompactionConfig(threshold_tokens=100, keep_recent_messages=2)
        msgs = [
            _user_msg("old msg"),
            _assistant_msg("old reply"),
            _tool_use_msg("t1", "read"),
            _tool_result_msg("t1", "file contents"),
            _user_msg("recent"), _assistant_msg("recent reply"),
        ]
        conv = _make_conversation(msgs, total_tokens=1000)

        fake_llm.set_text_response("extracted")
        fake_llm.set_text_response("summary")

        compactor = Compactor(config, fake_llm, memory_manager, conv)
        await compactor.maybe_compact()

        # No orphaned tool_result should exist
        for msg in conv.messages:
            for block in msg.content:
                if block.get("type") == "tool_result":
                    # There must be a preceding assistant with matching tool_use
                    idx = conv.messages.index(msg)
                    assert idx > 0
                    prev = conv.messages[idx - 1]
                    tool_ids = {b["id"] for b in prev.content if b.get("type") == "tool_use"}
                    assert block["tool_use_id"] in tool_ids


@pytest.mark.integration
class TestToolResultTruncation:
    """Large tool results get truncated during compaction."""

    async def test_large_tool_result_truncated(self, fake_llm, memory_manager):
        config = CompactionConfig(threshold_tokens=100, keep_recent_messages=10)
        # Create a message with a huge tool result
        huge_content = "x" * 50000  # Way over _MAX_TOOL_RESULT_TOKENS
        msgs = [
            _tool_use_msg("t1", "read"),
            _tool_result_msg("t1", huge_content, tokens=10000),
        ]
        conv = _make_conversation(msgs, total_tokens=10000)

        fake_llm.set_text_response("extracted")
        # No summarize call needed (only 2 messages <= keep_recent)

        compactor = Compactor(config, fake_llm, memory_manager, conv)
        await compactor.maybe_compact(force=True)

        # The tool result should be truncated
        result_block = conv.messages[1].content[0]
        assert "truncated" in result_block["content"]
        assert len(result_block["content"]) < len(huge_content)

    def test_small_tool_result_unchanged(self):
        msg = _tool_result_msg("t1", "short result")
        result = Compactor._truncate_tool_results(msg)
        assert result.content[0]["content"] == "short result"


@pytest.mark.integration
class TestCompactionMemoryFlush:
    """Compaction extracts key info and saves to daily memory."""

    async def test_flush_saves_to_daily(self, fake_llm, memory_manager, tmp_path):
        config = CompactionConfig(threshold_tokens=100, keep_recent_messages=2)
        msgs = [
            _user_msg("fix the auth bug"),
            _assistant_msg("Fixed auth.py line 42"),
            _user_msg("thanks"), _assistant_msg("welcome"),
        ]
        conv = _make_conversation(msgs, total_tokens=1000)

        fake_llm.set_text_response("Key fact: fixed auth bug in auth.py")
        fake_llm.set_text_response("Summary: fixed auth bug")

        compactor = Compactor(config, fake_llm, memory_manager, conv)
        await compactor.maybe_compact()

        # Daily notes should contain the extracted info
        daily_content = await memory_manager.read_daily()
        assert "auth" in daily_content.lower() or "Key fact" in daily_content
