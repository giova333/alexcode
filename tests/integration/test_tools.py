"""Integration tests for the tool system: registry, executor, and built-in tools."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.tools.base import ToolError
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyTool:
    name = "dummy"
    description = "A dummy tool"
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    async def execute(self, **params) -> str:
        return f"dummy:{params.get('x', '')}"


class AnotherTool:
    name = "another"
    description = "Another tool"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, **params) -> str:
        return "another result"


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestToolRegistry:

    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)
        assert registry.get("dummy") is tool

    def test_get_missing_returns_none(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.unregister("dummy")
        assert registry.get("dummy") is None

    def test_list_names(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        names = registry.list_names()
        assert set(names) == {"dummy", "another"}

    def test_all_definitions(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        defs = registry.all_definitions()
        assert len(defs) == 1
        assert defs[0]["name"] == "dummy"
        assert "input_schema" in defs[0]

    def test_definitions_for_subset(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        defs = registry.definitions_for({"dummy"})
        assert len(defs) == 1
        assert defs[0]["name"] == "dummy"


# ---------------------------------------------------------------------------
# ToolExecutor
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestToolExecutor:

    async def test_execute_registered_tool(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        executor = ToolExecutor(registry)

        result = await executor.execute("dummy", {"x": "hello"})
        assert result == "dummy:hello"

    async def test_execute_unknown_tool_raises(self):
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        with pytest.raises(ToolError, match="Unknown tool"):
            await executor.execute("nonexistent", {})


# ---------------------------------------------------------------------------
# Built-in tools with real filesystem
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestBuiltinReadTool:

    async def test_read_file(self, tmp_path: Path):
        from agent.tools.builtin.read import ReadTool

        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        tool = ReadTool()
        result = await tool.execute(file_path=str(test_file))
        assert "line1" in result
        assert "line2" in result

    async def test_read_nonexistent(self, tmp_path: Path):
        from agent.tools.builtin.read import ReadTool

        tool = ReadTool()
        result = await tool.execute(file_path=str(tmp_path / "nope.txt"))
        # Should return an error message, not crash
        assert "error" in result.lower() or "not found" in result.lower() or "no such" in result.lower()


@pytest.mark.integration
class TestBuiltinWriteTool:

    async def test_write_file(self, tmp_path: Path):
        from agent.tools.builtin.write import WriteTool

        tool = WriteTool()
        target = tmp_path / "output.txt"
        result = await tool.execute(file_path=str(target), content="hello world")
        assert target.exists()
        assert target.read_text() == "hello world"


@pytest.mark.integration
class TestBuiltinEditTool:

    async def test_edit_file(self, tmp_path: Path):
        from agent.tools.builtin.edit import EditTool

        target = tmp_path / "edit_me.txt"
        target.write_text("foo bar baz\n")

        tool = EditTool()
        result = await tool.execute(
            file_path=str(target),
            old_string="bar",
            new_string="BAR",
        )
        assert target.read_text() == "foo BAR baz\n"


@pytest.mark.integration
class TestBuiltinGlobTool:

    async def test_glob_finds_files(self, tmp_path: Path):
        from agent.tools.builtin.glob_tool import GlobTool

        (tmp_path / "a.py").write_text("# a")
        (tmp_path / "b.py").write_text("# b")
        (tmp_path / "c.txt").write_text("c")

        tool = GlobTool()
        result = await tool.execute(pattern="*.py", path=str(tmp_path))
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result


@pytest.mark.integration
class TestBuiltinGrepTool:

    async def test_grep_finds_content(self, tmp_path: Path):
        from agent.tools.builtin.grep import GrepTool

        (tmp_path / "file.py").write_text("def hello():\n    return 'world'\n")

        tool = GrepTool()
        result = await tool.execute(pattern="hello", path=str(tmp_path))
        assert "hello" in result


@pytest.mark.integration
class TestBuiltinBashTool:

    async def test_bash_simple_command(self):
        from agent.tools.builtin.bash import BashTool

        tool = BashTool(timeout=10)
        result = await tool.execute(command="echo 'hello from bash'")
        assert "hello from bash" in result

    async def test_bash_exit_code(self):
        from agent.tools.builtin.bash import BashTool

        tool = BashTool(timeout=10)
        result = await tool.execute(command="exit 1")
        assert "Exit code: 1" in result

    async def test_bash_timeout(self):
        from agent.tools.builtin.bash import BashTool

        tool = BashTool(timeout=1)
        result = await tool.execute(command="sleep 10", timeout=1)
        assert "timed out" in result.lower()


# ---------------------------------------------------------------------------
# Memory tools end-to-end through executor
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMemoryToolsE2E:
    """Memory tools called through ToolRegistry/ToolExecutor like the agent does."""

    async def test_memory_save_and_search(self, memory_manager, tmp_path):
        from agent.tools.builtin.memory_tool import MemorySaveTool, MemorySearchTool

        registry = ToolRegistry()
        registry.register(MemorySaveTool(memory_manager))
        registry.register(MemorySearchTool(memory_manager))
        executor = ToolExecutor(registry)

        # Save via tool
        result = await executor.execute("memory_save", {
            "content": "The project uses Redis for caching",
            "target": "daily",
        })
        assert "Saved" in result

        # Search via tool
        result = await executor.execute("memory_search", {"query": "Redis"})
        assert "Redis" in result

    async def test_memory_save_to_main(self, memory_manager, tmp_path):
        from agent.tools.builtin.memory_tool import MemorySaveTool, MemoryReadTool

        registry = ToolRegistry()
        registry.register(MemorySaveTool(memory_manager))
        registry.register(MemoryReadTool(memory_manager))
        executor = ToolExecutor(registry)

        await executor.execute("memory_save", {
            "content": "Always use type hints",
            "target": "main",
        })

        result = await executor.execute("memory_read", {"target": "main"})
        assert "type hints" in result

    async def test_memory_read_daily(self, memory_manager, tmp_path):
        from agent.tools.builtin.memory_tool import MemorySaveTool, MemoryReadTool

        registry = ToolRegistry()
        registry.register(MemorySaveTool(memory_manager))
        registry.register(MemoryReadTool(memory_manager))
        executor = ToolExecutor(registry)

        await executor.execute("memory_save", {"content": "Fixed auth bug"})
        result = await executor.execute("memory_read", {"target": "daily"})
        assert "Fixed auth bug" in result

    async def test_memory_read_dates(self, memory_manager, tmp_path):
        from agent.tools.builtin.memory_tool import MemorySaveTool, MemoryReadTool
        from datetime import date

        registry = ToolRegistry()
        registry.register(MemorySaveTool(memory_manager))
        registry.register(MemoryReadTool(memory_manager))
        executor = ToolExecutor(registry)

        await executor.execute("memory_save", {"content": "note"})
        result = await executor.execute("memory_read", {"target": "dates"})
        assert date.today().isoformat() in result

    async def test_memory_search_no_results(self, memory_manager, tmp_path):
        from agent.tools.builtin.memory_tool import MemorySearchTool

        registry = ToolRegistry()
        registry.register(MemorySearchTool(memory_manager))
        executor = ToolExecutor(registry)

        result = await executor.execute("memory_search", {"query": "nonexistent_xyz"})
        assert "No matching" in result
