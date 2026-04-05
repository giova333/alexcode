"""Tests for the subagent tool: runner, manager, and tool integration."""

from __future__ import annotations

import asyncio
import json

import pytest

from agent.config import Config
from agent.subagent.runner import SubagentRunner
from agent.tools.builtin.subagent import SubagentManager, SubagentTool, _EXCLUDED_TOOLS
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry
from tests.integration.conftest import FakeLLMProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class EchoTool:
    """A trivial tool that echoes its input for testing."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo the input text."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, *, text: str = "", **_) -> str:
        return f"echo: {text}"


class FailTool:
    """A tool that always raises."""

    @property
    def name(self) -> str:
        return "fail"

    @property
    def description(self) -> str:
        return "Always fails."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **_) -> str:
        raise RuntimeError("boom")


def _build_registry(*tools) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ===========================================================================
# ToolRegistry.clone_excluding
# ===========================================================================


class TestCloneExcluding:
    def test_excludes_specified_tools(self):
        echo = EchoTool()
        fail = FailTool()
        reg = _build_registry(echo, fail)

        cloned = reg.clone_excluding({"fail"})

        assert "echo" in cloned.list_names()
        assert "fail" not in cloned.list_names()

    def test_empty_exclusion_copies_all(self):
        reg = _build_registry(EchoTool(), FailTool())
        cloned = reg.clone_excluding(set())
        assert set(cloned.list_names()) == {"echo", "fail"}

    def test_exclude_all(self):
        reg = _build_registry(EchoTool())
        cloned = reg.clone_excluding({"echo"})
        assert cloned.list_names() == []

    def test_original_unchanged(self):
        reg = _build_registry(EchoTool(), FailTool())
        reg.clone_excluding({"echo"})
        assert "echo" in reg.list_names()


# ===========================================================================
# SubagentRunner
# ===========================================================================


class TestSubagentRunner:
    @pytest.fixture
    def llm(self) -> FakeLLMProvider:
        return FakeLLMProvider()

    def _make_runner(
        self, llm: FakeLLMProvider, test_config: Config, tools: list | None = None,
    ) -> SubagentRunner:
        registry = ToolRegistry()
        if tools:
            for t in tools:
                registry.register(t)
        return SubagentRunner(
            llm=llm,
            tool_registry=registry,
            tool_executor=ToolExecutor(registry),
            config=test_config,
            system_prompt="You are a test subagent.",
        )

    @pytest.mark.asyncio
    async def test_simple_text_response(self, llm, test_config):
        llm.set_text_response("Hello from subagent!")
        runner = self._make_runner(llm, test_config)

        result = await runner.run("Say hello")
        assert result == "Hello from subagent!"

    @pytest.mark.asyncio
    async def test_tool_use_then_text(self, llm, test_config):
        llm.set_tool_then_text(
            tool_name="echo",
            tool_input={"text": "ping"},
            final_text="Got echo result.",
        )
        runner = self._make_runner(llm, test_config, tools=[EchoTool()])

        result = await runner.run("Use echo tool")
        assert result == "Got echo result."
        assert len(llm.calls) == 2

    @pytest.mark.asyncio
    async def test_tool_error_is_captured(self, llm, test_config):
        llm.set_tool_then_text(
            tool_name="fail",
            tool_input={},
            final_text="Handled the error.",
        )
        runner = self._make_runner(llm, test_config, tools=[FailTool()])

        result = await runner.run("Try fail tool")
        assert result == "Handled the error."

        # Check the tool_result was sent as is_error
        second_call = llm.calls[1]
        tool_result_msg = second_call["messages"][-1]
        tool_result_block = tool_result_msg["content"][0]
        assert tool_result_block["is_error"] is True

    @pytest.mark.asyncio
    async def test_conversation_is_ephemeral(self, llm, test_config):
        llm.set_text_response("Response 1")
        runner = self._make_runner(llm, test_config)
        await runner.run("Task 1")

        # Conversation should have messages
        assert len(runner._conversation.messages) == 2  # user + assistant

        # A new runner starts fresh
        llm.set_text_response("Response 2")
        runner2 = self._make_runner(llm, test_config)
        await runner2.run("Task 2")
        assert len(runner2._conversation.messages) == 2

    @pytest.mark.asyncio
    async def test_max_iterations_safety(self, llm, test_config):
        """When the LLM keeps calling tools forever, the runner stops."""
        # Queue 51 tool_use responses (exceeding the 50 max)
        for i in range(51):
            llm.responses.append([
                from_tool_use_event("echo", {"text": f"iter-{i}"}, f"t_{i}"),
                response_complete(),
            ])
        runner = self._make_runner(llm, test_config, tools=[EchoTool()])
        result = await runner.run("Loop forever")
        assert "maximum iterations" in result.lower()


# ===========================================================================
# SubagentManager
# ===========================================================================


class TestSubagentManager:
    @pytest.mark.asyncio
    async def test_launch_returns_task_id(self):
        mgr = SubagentManager()

        async def dummy():
            return "done"

        tid = mgr.launch(dummy())
        assert tid == "subagent-1"
        await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_sequential_ids(self):
        mgr = SubagentManager()

        async def dummy():
            return "ok"

        t1 = mgr.launch(dummy())
        t2 = mgr.launch(dummy())
        assert t1 == "subagent-1"
        assert t2 == "subagent-2"
        await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_get_result_completed(self):
        mgr = SubagentManager()

        async def quick():
            return "result-value"

        tid = mgr.launch(quick())
        await asyncio.sleep(0.05)  # let the task complete

        result = mgr.get_result(tid)
        assert "completed" in result.lower()
        assert "result-value" in result

    @pytest.mark.asyncio
    async def test_get_result_running(self):
        mgr = SubagentManager()

        async def slow():
            await asyncio.sleep(10)
            return "never"

        tid = mgr.launch(slow())
        result = mgr.get_result(tid)
        assert "running" in result.lower()

        # Cleanup
        mgr._tasks[tid].cancel()

    @pytest.mark.asyncio
    async def test_get_result_failed(self):
        mgr = SubagentManager()

        async def fail():
            raise ValueError("test error")

        tid = mgr.launch(fail())
        await asyncio.sleep(0.05)

        result = mgr.get_result(tid)
        assert "failed" in result.lower()
        assert "test error" in result

    def test_get_result_unknown_id(self):
        mgr = SubagentManager()
        result = mgr.get_result("nonexistent")
        assert "unknown" in result.lower()

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        mgr = SubagentManager()

        async def quick():
            return "ok"

        async def slow():
            await asyncio.sleep(10)
            return "never"

        mgr.launch(quick())
        mgr.launch(slow())
        await asyncio.sleep(0.05)

        tasks = mgr.list_tasks()
        assert len(tasks) == 2
        statuses = {t["status"] for t in tasks}
        assert "completed" in statuses
        assert "running" in statuses

        # Cleanup
        for t in mgr._tasks.values():
            t.cancel()


# ===========================================================================
# SubagentTool
# ===========================================================================


class TestSubagentTool:
    @pytest.fixture
    def llm(self) -> FakeLLMProvider:
        return FakeLLMProvider()

    @pytest.fixture
    def parent_registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register(EchoTool())

        # Add fake "excluded" tools to verify filtering
        class FakeSubagent:
            name = "subagent"
            description = "self"
            input_schema = {"type": "object", "properties": {}}
            async def execute(self, **_): return ""

        class FakeMemorySave:
            name = "memory_save"
            description = "save"
            input_schema = {"type": "object", "properties": {}}
            async def execute(self, **_): return ""

        class FakeAskUser:
            name = "ask_user"
            description = "ask"
            input_schema = {"type": "object", "properties": {}}
            async def execute(self, **_): return ""

        reg.register(FakeSubagent())
        reg.register(FakeMemorySave())
        reg.register(FakeAskUser())
        return reg

    @pytest.fixture
    def tool(self, llm, parent_registry, test_config) -> SubagentTool:
        return SubagentTool(
            llm=llm,
            parent_registry=parent_registry,
            config=test_config,
            default_system_prompt="You are a test agent. CWD: {{CWD}} Time: {{LOCAL_TIME}}",
        )

    @pytest.mark.asyncio
    async def test_run_action(self, tool, llm):
        llm.set_text_response("Subagent says hi")
        result = await tool.execute(action="run", task="Say hi")
        assert result == "Subagent says hi"

    @pytest.mark.asyncio
    async def test_run_requires_task(self, tool):
        result = await tool.execute(action="run")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_launch_and_check(self, tool, llm):
        llm.set_text_response("Background result")
        result = await tool.execute(action="launch", task="Background work")
        assert "task_id" in result.lower()
        task_id = result.split(": ")[1]

        # Wait for completion
        await asyncio.sleep(0.1)

        check_result = await tool.execute(action="check", task_id=task_id)
        assert "completed" in check_result.lower()
        assert "Background result" in check_result

    @pytest.mark.asyncio
    async def test_launch_requires_task(self, tool):
        result = await tool.execute(action="launch")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_check_requires_task_id(self, tool):
        result = await tool.execute(action="check")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_list_empty(self, tool):
        result = await tool.execute(action="list")
        assert "no subagents" in result.lower()

    @pytest.mark.asyncio
    async def test_list_with_tasks(self, tool, llm):
        llm.set_text_response("Done 1")
        llm.set_text_response("Done 2")
        await tool.execute(action="launch", task="Task 1")
        await tool.execute(action="launch", task="Task 2")
        await asyncio.sleep(0.1)

        result = await tool.execute(action="list")
        tasks = json.loads(result)
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool):
        result = await tool.execute(action="unknown")
        assert "error" in result.lower()

    def test_excluded_tools_not_in_child_registry(self, tool):
        runner = tool._create_runner("test prompt")
        child_names = set(runner._tool_registry.list_names())
        assert "echo" in child_names
        for excluded in _EXCLUDED_TOOLS:
            assert excluded not in child_names

    @pytest.mark.asyncio
    async def test_custom_system_prompt(self, tool, llm):
        llm.set_text_response("Custom prompt response")
        await tool.execute(
            action="run",
            task="Do something",
            system_prompt="You are a custom agent.",
        )
        # Verify the LLM received the custom prompt
        assert llm.calls[0]["system"] == "You are a custom agent."

    @pytest.mark.asyncio
    async def test_default_system_prompt_has_placeholders_resolved(self, tool, llm):
        llm.set_text_response("ok")
        await tool.execute(action="run", task="test")
        system = llm.calls[0]["system"]
        assert "{{CWD}}" not in system
        assert "{{LOCAL_TIME}}" not in system

    @pytest.mark.asyncio
    async def test_concurrent_async_subagents(self, tool, llm):
        """Multiple async subagents can run concurrently."""
        # Each subagent gets its own text response
        for i in range(3):
            llm.set_text_response(f"Result {i}")

        task_ids = []
        for i in range(3):
            result = await tool.execute(action="launch", task=f"Task {i}")
            tid = result.split(": ")[1]
            task_ids.append(tid)

        await asyncio.sleep(0.2)

        for tid in task_ids:
            check = await tool.execute(action="check", task_id=tid)
            assert "completed" in check.lower()

    @pytest.mark.asyncio
    async def test_subagent_with_tool_use(self, tool, llm):
        """Subagent can use tools and return the final text."""
        llm.set_tool_then_text(
            tool_name="echo",
            tool_input={"text": "hello"},
            final_text="Echo returned hello.",
        )
        result = await tool.execute(action="run", task="Use echo")
        assert result == "Echo returned hello."


# ---------------------------------------------------------------------------
# Helpers for building stream events
# ---------------------------------------------------------------------------

def from_tool_use_event(name: str, input_data: dict, tool_id: str = "t_1"):
    from agent.llm.base import ToolUseEvent
    return ToolUseEvent(id=tool_id, name=name, input=input_data)


def response_complete(input_tokens: int = 100, output_tokens: int = 50):
    from agent.llm.base import ResponseComplete, UsageInfo
    return ResponseComplete(
        usage=UsageInfo(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="tool_use",
    )
