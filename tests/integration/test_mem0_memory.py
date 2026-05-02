"""Integration tests for the mem0-backed memory layer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent.config import Mem0Config, Mem0EmbedderConfig, Mem0LLMConfig, MemoryConfig
from agent.core.conversation import Conversation
from agent.core.message import Message
from agent.memory.manager import MemoryManager


class FakeMemory:
    """In-memory stand-in for mem0.Memory. Records every call."""

    instances: list["FakeMemory"] = []

    def __init__(self, collection: str, path: str) -> None:
        self.collection = collection
        self.path = path
        self.added: list[tuple[list[dict[str, Any]], str]] = []
        self._search_canned: list[dict[str, Any]] = []
        FakeMemory.instances.append(self)

    def add(self, messages: list[dict[str, Any]], user_id: str = "") -> None:
        self.added.append((messages, user_id))

    def search(self, query: str, user_id: str = "", limit: int = 10) -> dict[str, Any]:
        return {"results": list(self._search_canned[:limit])}


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeMemory.instances.clear()
    yield
    FakeMemory.instances.clear()


@pytest.fixture
def patch_mem0(monkeypatch):
    """Replace mem0.Memory.from_config with a FakeMemory factory."""

    class _StubMem0:
        @staticmethod
        def from_config(cfg: dict[str, Any]) -> FakeMemory:
            vs = cfg.get("vector_store", {}).get("config", {})
            return FakeMemory(vs.get("collection_name", ""), vs.get("path", ""))

    fake_module = type("M", (), {"Memory": _StubMem0})
    import sys

    monkeypatch.setitem(sys.modules, "mem0", fake_module)
    return fake_module


def _mem0_config(tmp_path: Path) -> Mem0Config:
    return Mem0Config(
        enabled=True,
        project_store_dir=str(tmp_path / "mem0_project"),
        global_store_dir=str(tmp_path / "mem0_global"),
        llm=Mem0LLMConfig(api_key="x"),
        embedder=Mem0EmbedderConfig(api_key="y"),
    )


@pytest.mark.integration
class TestMem0Client:

    async def test_project_scope_uses_project_user_id(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="project", project_dir=tmp_path)
        client.enqueue_turn([Message.user("hello"), Message.assistant("hi")])
        await client.aclose()

        mems = FakeMemory.instances
        assert len(mems) == 1
        assert mems[0].collection == "project_memories"
        # user_id should be the absolute project path.
        msgs, user_id = mems[0].added[0]
        assert user_id == str(tmp_path.resolve())
        assert msgs[0]["content"] == "hello"
        assert msgs[1]["content"] == "hi"

    async def test_global_scope_uses_global_user_id(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)
        client.enqueue_turn([Message.user("hello"), Message.assistant("hi")])
        await client.aclose()

        mems = FakeMemory.instances
        assert len(mems) == 1
        assert mems[0].collection == "global_memories"
        _, user_id = mems[0].added[0]
        assert user_id == "global"

    async def test_invalid_scope_raises(self, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        with pytest.raises(ValueError):
            Mem0Client(_mem0_config(tmp_path), scope="bogus", project_dir=tmp_path)

    async def test_turn_is_batched_into_single_add_call(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)
        client.enqueue_turn([
            Message.user("hello world"),
            Message.assistant("hi back"),
        ])
        await client.aclose()

        # One turn → one mem0.add() call carrying both messages.
        added = FakeMemory.instances[0].added
        assert len(added) == 1
        msgs, _ = added[0]
        contents = [m["content"] for m in msgs]
        assert contents == ["hello world", "hi back"]

    async def test_tool_results_and_empty_messages_are_filtered(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)

        tool_use_msg = Message(
            role="assistant",
            content=[{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
        )
        tool_result_msg = Message.tool_result("t1", "big output", is_error=False)
        blank_msg = Message.user("   ")

        client.enqueue_turn([tool_use_msg, tool_result_msg, blank_msg])
        await client.aclose()

        # All blocks were filtered → nothing was queued, no Memory built.
        if FakeMemory.instances:
            assert FakeMemory.instances[0].added == []

    async def test_search_labels_results_with_scope(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)

        # Force lazy init.
        await client.search("warmup", top_k=1)

        FakeMemory.instances[0]._search_canned = [
            {"memory": "fact A", "score": 0.6},
            {"memory": "fact B", "score": 0.9},
        ]

        results = await client.search("anything", top_k=5)
        assert all(r["source"] == "global" for r in results)
        # Higher score first.
        assert results[0]["text"] == "fact B"


@pytest.mark.integration
class TestMemoryManagerTurnIngestion:

    async def test_ingest_turn_batches_user_and_assistant_into_one_add(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        mem0_client = Mem0Client(_mem0_config(tmp_path), scope="project", project_dir=tmp_path)
        mgr = MemoryManager(
            MemoryConfig(memory_file=".agent/memory/MEMORY.md"),
            tmp_path,
            mem0_client=mem0_client,
        )

        user_msg = Message.user("first message")
        assistant_msg = Message.assistant("first reply")
        tool_use_msg = Message(
            role="assistant",
            content=[{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
        )
        tool_result_msg = Message.tool_result("t1", "result", is_error=False)

        # Simulate a turn with an intermediate tool_use → tool_result → final reply.
        mgr.ingest_turn(user_msg, [tool_use_msg, assistant_msg])
        # Tool-result messages live in the conversation but are NOT part of an
        # ingested turn — they're noise for memory extraction.
        await mem0_client.aclose()

        added = FakeMemory.instances[0].added
        assert len(added) == 1, "expected one batched mem0.add() per turn"
        msgs, _ = added[0]
        contents = [m["content"] for m in msgs]
        assert contents == ["first message", "first reply"]
        assert "result" not in contents

    async def test_ingest_turn_with_no_text_is_a_noop(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        mem0_client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)
        mgr = MemoryManager(
            MemoryConfig(memory_file=".agent/memory/MEMORY.md"),
            tmp_path,
            mem0_client=mem0_client,
        )

        # Empty user text + tool-only assistant message → nothing to ingest.
        mgr.ingest_turn(
            Message.user("   "),
            [Message(role="assistant", content=[{"type": "tool_use", "id": "t", "name": "x", "input": {}}])],
        )
        await asyncio.sleep(0)
        await mem0_client.aclose()

        if FakeMemory.instances:
            assert FakeMemory.instances[0].added == []
