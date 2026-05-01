"""Integration tests for the memory system: MEMORY.md I/O and MemoryManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.memory.files import MemoryFiles
from agent.memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# MemoryFiles (MEMORY.md)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMemoryFiles:

    def test_read_empty(self, tmp_path: Path):
        files = MemoryFiles(".agent/memory/MEMORY.md", tmp_path)
        assert files.read() == ""

    def test_write_and_read(self, tmp_path: Path):
        files = MemoryFiles(".agent/memory/MEMORY.md", tmp_path)
        files.write("# Project Memory\n- Python 3.13")
        assert "Python 3.13" in files.read()

    def test_append(self, tmp_path: Path):
        files = MemoryFiles(".agent/memory/MEMORY.md", tmp_path)
        files.write("Line 1")
        files.append("Line 2")
        content = files.read()
        assert "Line 1" in content
        assert "Line 2" in content

    def test_creates_directories(self, tmp_path: Path):
        files = MemoryFiles("deep/nested/dir/MEMORY.md", tmp_path)
        files.write("test")
        assert (tmp_path / "deep/nested/dir/MEMORY.md").exists()


# ---------------------------------------------------------------------------
# MemoryManager (without a Mem0Client — covers MEMORY.md path only)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMemoryManager:

    async def test_load_context_empty(self, memory_manager: MemoryManager):
        ctx = await memory_manager.load_context()
        assert ctx == ""

    async def test_save_and_read_main(self, memory_manager: MemoryManager):
        result = await memory_manager.save_main("Project uses Python 3.13")
        assert "Saved" in result

        content = await memory_manager.read_main()
        assert "Python 3.13" in content

    async def test_load_context_returns_main(self, memory_manager: MemoryManager):
        await memory_manager.save_main("Main memory content")
        ctx = await memory_manager.load_context()
        assert "Main memory content" in ctx

    async def test_search_without_mem0_returns_empty(self, memory_manager: MemoryManager):
        await memory_manager.save_main("The database uses PostgreSQL with read replicas")
        results = await memory_manager.search("PostgreSQL")
        assert results == []

