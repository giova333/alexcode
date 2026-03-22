"""Integration tests for conversation history storage and session management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.compaction.compactor import Compactor
from agent.config import CompactionConfig
from agent.core.conversation import Conversation
from agent.core.message import Message
from agent.history.storage import HistoryStorage


@pytest.mark.integration
class TestHistorySaveLoad:
    """Save and load conversations as JSONL."""

    def test_save_and_load_messages(self, history_storage: HistoryStorage):
        sid = history_storage.new_session_id()
        msgs = [
            Message.user("Hello"),
            Message.assistant("Hi there!"),
        ]
        msgs[0].token_count = 10
        msgs[1].token_count = 15

        history_storage.save(sid, msgs)
        loaded = history_storage.load(sid)

        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[0].text == "Hello"
        assert loaded[0].token_count == 10
        assert loaded[1].role == "assistant"
        assert loaded[1].text == "Hi there!"

    def test_incremental_save(self, history_storage: HistoryStorage):
        sid = history_storage.new_session_id()
        msgs = [Message.user("msg1")]
        msgs[0].token_count = 5
        history_storage.save(sid, msgs)

        # Add more messages
        msgs.append(Message.assistant("reply1"))
        msgs[1].token_count = 8
        history_storage.save(sid, msgs)

        loaded = history_storage.load(sid)
        assert len(loaded) == 2

    def test_rewrite_after_compaction(self, history_storage: HistoryStorage):
        sid = history_storage.new_session_id()
        original = [Message.user(f"msg{i}") for i in range(5)]
        for m in original:
            m.token_count = 10
        history_storage.save(sid, original)

        # Rewrite with fewer messages (simulating compaction)
        compacted = [Message.user("[Summary]"), Message.user("recent")]
        for m in compacted:
            m.token_count = 20
        history_storage.rewrite(sid, compacted)

        loaded = history_storage.load(sid)
        assert len(loaded) == 2
        assert loaded[0].text == "[Summary]"

    def test_load_nonexistent_returns_none(self, history_storage: HistoryStorage):
        assert history_storage.load("nonexistent_session") is None


@pytest.mark.integration
class TestSessionManagement:
    """Session listing, finding, clearing."""

    def test_list_sessions(self, history_storage: HistoryStorage):
        for i in range(3):
            sid = f"session_{i}"
            msgs = [Message.user(f"msg {i}")]
            msgs[0].token_count = 5
            history_storage.save(sid, msgs)

        sessions = history_storage.list_sessions()
        assert len(sessions) == 3
        for s in sessions:
            assert "session_id" in s
            assert "message_count" in s

    def test_find_session_exact(self, history_storage: HistoryStorage):
        sid = "test_session_abc"
        history_storage.save(sid, [Message.user("hi")])
        assert history_storage.find_session("test_session_abc") == sid

    def test_find_session_prefix(self, history_storage: HistoryStorage):
        sid = "test_session_prefix_123"
        history_storage.save(sid, [Message.user("hi")])
        found = history_storage.find_session("test_session_prefix")
        assert found == sid

    def test_find_session_not_found(self, history_storage: HistoryStorage):
        assert history_storage.find_session("nonexistent") is None

    def test_get_latest_session(self, history_storage: HistoryStorage):
        history_storage.save("old_session", [Message.user("old")])
        history_storage.save("new_session", [Message.user("new")])

        latest = history_storage.get_latest_session_id()
        assert latest is not None

    def test_clear_session(self, history_storage: HistoryStorage):
        sid = "clear_me"
        msgs = [Message.user("msg1"), Message.assistant("reply1")]
        for m in msgs:
            m.token_count = 10
        history_storage.save(sid, msgs)

        history_storage.clear_session(sid)
        loaded = history_storage.load(sid)
        # After clearing, should have no messages (or None)
        assert loaded is None or len(loaded) == 0


@pytest.mark.integration
class TestSessionResume:
    """Resume a session through the agent loop."""

    async def test_resume_loads_messages(self, fake_llm, fake_cli, test_config, tmp_path):
        from agent.core.loop import AgentLoop
        from agent.tools.builtin.update_plan import UpdatePlanTool

        history = HistoryStorage(test_config.history.dir, tmp_path)
        update_plan = UpdatePlanTool()

        # Create agent, send a message, save
        fake_llm.set_text_response("First response")
        agent1 = AgentLoop(
            config=test_config, llm=fake_llm, cli=fake_cli,
            project_dir=tmp_path, history=history, update_plan_tool=update_plan,
        )
        await agent1._process_message("First question")
        sid = agent1._session_id
        agent1._save_history()

        # New agent resumes the session
        agent2 = AgentLoop(
            config=test_config, llm=fake_llm, cli=fake_cli,
            project_dir=tmp_path, history=history, update_plan_tool=update_plan,
        )
        success = agent2.resume_session(sid)
        assert success is True
        assert len(agent2._conversation.messages) == 2
        assert agent2._conversation.messages[0].text == "First question"

    async def test_resume_after_compaction(self, fake_llm, fake_cli, test_config, tmp_path, memory_manager):
        """Session resume works correctly after compaction has rewritten history."""
        from agent.core.loop import AgentLoop
        from agent.tools.builtin.update_plan import UpdatePlanTool

        history = HistoryStorage(test_config.history.dir, tmp_path)
        update_plan = UpdatePlanTool()

        # Build first agent, fill conversation
        fake_llm.set_text_response("reply 1")
        fake_llm.set_text_response("reply 2")
        fake_llm.set_text_response("reply 3")
        agent1 = AgentLoop(
            config=test_config, llm=fake_llm, cli=fake_cli,
            project_dir=tmp_path, history=history,
            memory_manager=memory_manager, update_plan_tool=update_plan,
        )
        await agent1._process_message("msg 1")
        await agent1._process_message("msg 2")
        await agent1._process_message("msg 3")
        sid = agent1._session_id
        agent1._save_history()

        assert len(agent1._conversation.messages) == 6

        # Force compaction (adds extract + summarize LLM calls)
        fake_llm.set_text_response("extracted key facts")
        fake_llm.set_text_response("Summary of old messages")
        compacted = await agent1._compactor.maybe_compact(force=True)
        assert compacted is True
        history.rewrite(sid, agent1._conversation.messages)

        # Resume with new agent
        agent2 = AgentLoop(
            config=test_config, llm=fake_llm, cli=fake_cli,
            project_dir=tmp_path, history=history, update_plan_tool=update_plan,
        )
        success = agent2.resume_session(sid)
        assert success is True
        # First message should be the compaction summary
        assert "[Previous conversation summary]" in agent2._conversation.messages[0].text


@pytest.mark.integration
class TestCorruptedHistory:
    """History loading with malformed JSONL data."""

    def test_load_with_corrupted_lines(self, history_storage: HistoryStorage, tmp_path):
        """Corrupted JSONL lines should be skipped, valid messages still loaded."""
        sid = "corrupted_session"
        path = tmp_path / ".agent/history" / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            json.dumps({"type": "header", "session_id": sid, "timestamp": "2025-01-01", "metadata": {}}),
            "this is not valid json",
            json.dumps({"type": "message", "role": "user", "content": [{"type": "text", "text": "hello"}], "token_count": 5}),
            "{broken json",
            json.dumps({"type": "message", "role": "assistant", "content": [{"type": "text", "text": "hi"}], "token_count": 8}),
        ]
        path.write_text("\n".join(lines) + "\n")

        loaded = history_storage.load(sid)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].text == "hello"
        assert loaded[1].text == "hi"
