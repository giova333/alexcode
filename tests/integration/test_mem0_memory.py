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
        client.enqueue_message(Message.user("hello"))
        await client.aclose()

        mems = FakeMemory.instances
        assert len(mems) == 1
        assert mems[0].collection == "project_memories"
        # user_id should be the absolute project path.
        msgs, user_id = mems[0].added[0]
        assert user_id == str(tmp_path.resolve())
        assert msgs[0]["content"] == "hello"

    async def test_global_scope_uses_global_user_id(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)
        client.enqueue_message(Message.user("hello"))
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

    async def test_user_and_assistant_text_are_ingested(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)
        client.enqueue_message(Message.user("hello world"))
        client.enqueue_message(Message.assistant("hi back"))
        await client.aclose()

        added = [msgs[0]["content"] for msgs, _ in FakeMemory.instances[0].added]
        assert "hello world" in added
        assert "hi back" in added

    async def test_tool_results_and_empty_messages_are_skipped(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)

        tool_use_msg = Message(
            role="assistant",
            content=[{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
        )
        tool_result_msg = Message.tool_result("t1", "big output", is_error=False)
        blank_msg = Message.user("   ")

        client.enqueue_message(tool_use_msg)
        client.enqueue_message(tool_result_msg)
        client.enqueue_message(blank_msg)

        await client.aclose()

        # Nothing was eligible for ingestion → no Memory was instantiated.
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
class TestConversationHookIntegration:

    async def test_conversation_append_forwards_user_text_to_mem0(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        mem0_client = Mem0Client(_mem0_config(tmp_path), scope="project", project_dir=tmp_path)
        mgr = MemoryManager(
            MemoryConfig(memory_file=".agent/memory/MEMORY.md"),
            tmp_path,
            mem0_client=mem0_client,
        )

        conv = Conversation(on_append=mgr.handle_message_appended)
        conv.append(Message.user("first message"))
        conv.append(Message.assistant("first reply"))
        conv.append(Message.tool_result("t1", "result", is_error=False))

        await mem0_client.aclose()

        contents = [msgs[0]["content"] for msgs, _ in FakeMemory.instances[0].added]
        assert "first message" in contents
        assert "first reply" in contents
        assert "result" not in contents

    async def test_load_messages_does_not_re_ingest(self, patch_mem0, tmp_path):
        from agent.memory.mem0_client import Mem0Client

        mem0_client = Mem0Client(_mem0_config(tmp_path), scope="global", project_dir=tmp_path)
        mgr = MemoryManager(
            MemoryConfig(memory_file=".agent/memory/MEMORY.md"),
            tmp_path,
            mem0_client=mem0_client,
        )

        conv = Conversation(on_append=mgr.handle_message_appended)
        conv.load_messages([Message.user("from history"), Message.assistant("old reply")])

        await asyncio.sleep(0)
        await mem0_client.aclose()

        if FakeMemory.instances:
            assert FakeMemory.instances[0].added == []
