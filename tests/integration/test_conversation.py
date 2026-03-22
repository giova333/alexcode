"""Integration tests for conversation state management and message handling."""

from __future__ import annotations

import pytest

from agent.core.conversation import Conversation, sanitize_tool_pairs
from agent.core.message import Message
from agent.core.tokens import count_tokens, count_message_tokens


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMessage:

    def test_user_message(self):
        msg = Message.user("hello")
        assert msg.role == "user"
        assert msg.text == "hello"
        assert msg.content == [{"type": "text", "text": "hello"}]

    def test_assistant_message(self):
        msg = Message.assistant("reply")
        assert msg.role == "assistant"
        assert msg.text == "reply"

    def test_tool_result_message(self):
        msg = Message.tool_result("tool_123", "result text", is_error=True)
        assert msg.role == "user"
        assert msg.content[0]["type"] == "tool_result"
        assert msg.content[0]["tool_use_id"] == "tool_123"
        assert msg.content[0]["is_error"] is True

    def test_text_concatenation(self):
        msg = Message(role="assistant", content=[
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ])
        assert msg.text == "Hello world"

    def test_to_dict(self):
        msg = Message.user("test")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == [{"type": "text", "text": "test"}]


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestConversation:

    def test_append_and_track_tokens(self):
        conv = Conversation()
        msg = Message.user("hi")
        msg.token_count = 42
        conv.append(msg)

        assert len(conv.messages) == 1
        assert conv.total_tokens == 42

    def test_clear(self):
        conv = Conversation()
        msg = Message.user("hi")
        msg.token_count = 10
        conv.append(msg)
        conv.clear()

        assert len(conv.messages) == 0
        assert conv.total_tokens == 0

    def test_to_api_messages(self):
        conv = Conversation()
        conv.append(Message.user("hello"))
        conv.append(Message.assistant("hi"))

        api = conv.to_api_messages()
        assert len(api) == 2
        assert api[0]["role"] == "user"
        assert api[1]["role"] == "assistant"

    def test_load_messages_recalculates_tokens(self):
        msgs = [Message.user("a"), Message.assistant("b")]
        msgs[0].token_count = 10
        msgs[1].token_count = 20

        conv = Conversation()
        conv.load_messages(msgs)
        assert conv.total_tokens == 30


# ---------------------------------------------------------------------------
# Sanitize tool pairs
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSanitizeToolPairs:

    def test_valid_pairs_unchanged(self):
        msgs = [
            Message(role="assistant", content=[
                {"type": "tool_use", "id": "t1", "name": "read", "input": {}}
            ]),
            Message(role="user", content=[
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
            ]),
        ]
        result = sanitize_tool_pairs(msgs)
        assert len(result) == 2
        assert result[1].content[0]["type"] == "tool_result"

    def test_orphaned_tool_result_converted(self):
        # tool_result without preceding tool_use
        msgs = [
            Message.user("some text"),
            Message(role="user", content=[
                {"type": "tool_result", "tool_use_id": "orphan_id", "content": "orphan result"}
            ]),
        ]
        result = sanitize_tool_pairs(msgs)
        assert len(result) == 2
        # The orphaned tool_result should be converted to text
        assert result[1].content[0]["type"] == "text"
        assert "orphan result" in result[1].text

    def test_mismatched_id_converted(self):
        msgs = [
            Message(role="assistant", content=[
                {"type": "tool_use", "id": "t1", "name": "read", "input": {}}
            ]),
            Message(role="user", content=[
                {"type": "tool_result", "tool_use_id": "wrong_id", "content": "result"}
            ]),
        ]
        result = sanitize_tool_pairs(msgs)
        # The tool_result with wrong ID should be converted
        assert result[1].content[0]["type"] == "text"

    def test_plain_messages_unchanged(self):
        msgs = [Message.user("hello"), Message.assistant("hi")]
        result = sanitize_tool_pairs(msgs)
        assert len(result) == 2
        assert result[0].text == "hello"


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestTokenCounting:

    def test_count_tokens_basic(self):
        tokens = count_tokens("Hello, world!")
        assert tokens > 0
        assert tokens < 20

    def test_count_tokens_empty(self):
        assert count_tokens("") == 0

    def test_count_message_tokens(self):
        msg = {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
        tokens = count_message_tokens(msg)
        assert tokens > 4  # At least overhead

    def test_count_message_tokens_string_content(self):
        msg = {"role": "user", "content": "Hello"}
        tokens = count_message_tokens(msg)
        assert tokens > 0
