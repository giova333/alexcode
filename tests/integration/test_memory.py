"""Integration tests for the memory system: save, read, search, daily notes."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from agent.config import EmbeddingConfig, MemoryConfig
from agent.memory.daily import DailyMemory
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
# DailyMemory
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDailyMemory:

    def test_append_and_read_today(self, tmp_path: Path):
        daily = DailyMemory(".agent/memory/daily/", tmp_path)
        daily.append("Session started: working on tests")
        content = daily.read_today()
        assert "Session started" in content
        assert date.today().isoformat() in content

    def test_multiple_entries(self, tmp_path: Path):
        daily = DailyMemory(".agent/memory/daily/", tmp_path)
        daily.append("Entry 1")
        daily.append("Entry 2")
        content = daily.read_today()
        assert "Entry 1" in content
        assert "Entry 2" in content

    def test_read_specific_date(self, tmp_path: Path):
        daily = DailyMemory(".agent/memory/daily/", tmp_path)
        # Manually create a file for a specific date
        target = date(2025, 6, 15)
        file_path = tmp_path / ".agent/memory/daily" / f"{target.isoformat()}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("# Daily Notes — 2025-06-15\nOld notes here")

        content = daily.read_date(target)
        assert "Old notes here" in content

    def test_read_recent(self, tmp_path: Path):
        daily = DailyMemory(".agent/memory/daily/", tmp_path)
        # Create today's file
        daily.append("Today's note")
        # Create yesterday's file manually
        yesterday = date.today() - timedelta(days=1)
        yfile = tmp_path / ".agent/memory/daily" / f"{yesterday.isoformat()}.md"
        yfile.parent.mkdir(parents=True, exist_ok=True)
        yfile.write_text("Yesterday's note")

        recent = daily.read_recent(days=2)
        assert len(recent) == 2
        dates = [dt for dt, _ in recent]
        assert date.today() in dates
        assert yesterday in dates

    def test_list_dates(self, tmp_path: Path):
        daily = DailyMemory(".agent/memory/daily/", tmp_path)
        daily.append("note")
        dates = daily.list_dates()
        assert date.today().isoformat() in dates


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMemoryManager:

    async def test_load_context_empty(self, memory_manager: MemoryManager):
        ctx = await memory_manager.load_context()
        assert ctx == ""

    async def test_save_and_load_daily(self, memory_manager: MemoryManager):
        result = await memory_manager.save_daily("Important finding: API uses v2")
        assert "Saved" in result

        ctx = await memory_manager.load_context()
        assert "API uses v2" in ctx

    async def test_save_and_load_main(self, memory_manager: MemoryManager):
        result = await memory_manager.save_main("Project uses Python 3.13")
        assert "Saved" in result

        content = await memory_manager.read_main()
        assert "Python 3.13" in content

    async def test_context_includes_both_sources(self, memory_manager: MemoryManager):
        await memory_manager.save_main("Main memory content")
        await memory_manager.save_daily("Daily note content")

        ctx = await memory_manager.load_context()
        assert "Main memory content" in ctx
        assert "Daily note content" in ctx

    async def test_fallback_search(self, memory_manager: MemoryManager):
        await memory_manager.save_main("The database uses PostgreSQL with read replicas")
        await memory_manager.save_daily("Fixed a bug in the auth middleware")

        results = await memory_manager.search("PostgreSQL")
        assert len(results) > 0
        assert any("PostgreSQL" in r["text"] for r in results)

    async def test_fallback_search_no_results(self, memory_manager: MemoryManager):
        await memory_manager.save_main("Some content")
        results = await memory_manager.search("nonexistent_keyword_xyz")
        assert len(results) == 0

    async def test_read_daily_today(self, memory_manager: MemoryManager):
        await memory_manager.save_daily("Today's entry")
        content = await memory_manager.read_daily()
        assert "Today's entry" in content

    async def test_list_daily_dates(self, memory_manager: MemoryManager):
        await memory_manager.save_daily("note")
        dates = await memory_manager.list_daily_dates()
        assert date.today().isoformat() in dates
