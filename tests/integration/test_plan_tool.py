"""Tests for the plan tool: read-only subagent with CLI streaming."""

from __future__ import annotations

import pytest

from agent.config import Config
from agent.subagent.runner import SubagentRunner
from agent.tools.builtin.plan import PlanTool, _PLAN_TOOLS
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry
from tests.integration.conftest import FakeCLI, FakeLLMProvider


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


class FakeReadTool:
    """Fake read tool for testing."""

    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return "Read a file."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    async def execute(self, *, path: str = "", **_) -> str:
        return f"contents of {path}"


class FakeMCPTool:
    """Fake MCP tool to test MCP tool passthrough."""

    @property
    def name(self) -> str:
        return "mcp__glean__search"

    @property
    def description(self) -> str:
        return "Search via Glean MCP."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"query": {"type": "string"}}}

    async def execute(self, **_) -> str:
        return "mcp result"


def _build_registry(*tools) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ===========================================================================
# PlanTool
# ===========================================================================


@pytest.mark.integration
class TestPlanTool:
    """Integration tests for the PlanTool subagent."""

    async def test_execute_returns_plan_text(self, test_config: Config):
        llm = FakeLLMProvider()
        llm.set_text_response("## Implementation Plan\n1. Do X\n2. Do Y")
        cli = FakeCLI()
        registry = _build_registry(FakeReadTool(), EchoTool())

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        result = await tool.execute(task="Plan how to add feature X")

        assert "Implementation Plan" in result
        assert "Do X" in result

    async def test_requires_task(self, test_config: Config):
        llm = FakeLLMProvider()
        cli = FakeCLI()
        registry = _build_registry()

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        result = await tool.execute(task="")

        assert "Error" in result
        assert "task" in result.lower()

    async def test_read_only_tools_only(self, test_config: Config):
        """Child registry should contain only allowed read-only tools, not write/edit/etc."""
        llm = FakeLLMProvider()
        cli = FakeCLI()

        # Parent has both allowed and disallowed tools
        class WriteTool:
            name = "write"
            description = "Write a file."
            input_schema = {"type": "object", "properties": {}}
            async def execute(self, **_): return "ok"

        class EditTool:
            name = "edit"
            description = "Edit a file."
            input_schema = {"type": "object", "properties": {}}
            async def execute(self, **_): return "ok"

        class SubagentToolFake:
            name = "subagent"
            description = "Delegate."
            input_schema = {"type": "object", "properties": {}}
            async def execute(self, **_): return "ok"

        registry = _build_registry(
            FakeReadTool(), EchoTool(), WriteTool(), EditTool(), SubagentToolFake(),
        )

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        runner = tool._create_runner()

        child_names = set(runner._tool_registry.list_names())
        # read is in _PLAN_TOOLS so should be included
        assert "read" in child_names
        # echo, write, edit, subagent are NOT in _PLAN_TOOLS
        assert "echo" not in child_names
        assert "write" not in child_names
        assert "edit" not in child_names
        assert "subagent" not in child_names

    async def test_mcp_tools_included(self, test_config: Config):
        """MCP tools (mcp__*) should be passed through to the child registry."""
        llm = FakeLLMProvider()
        cli = FakeCLI()
        registry = _build_registry(FakeReadTool(), FakeMCPTool())

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        runner = tool._create_runner()

        child_names = set(runner._tool_registry.list_names())
        assert "read" in child_names
        assert "mcp__glean__search" in child_names

    async def test_cli_streaming(self, test_config: Config):
        """CLI methods should be called during plan execution."""
        llm = FakeLLMProvider()
        llm.set_text_response("Here is the plan.")
        cli = FakeCLI()
        registry = _build_registry(FakeReadTool())

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        await tool.execute(task="Plan something")

        # Text delta should have been streamed
        assert "Here is the plan." in "".join(cli.output)

    async def test_tool_use_then_text(self, test_config: Config):
        """Plan agent uses a tool (read), then returns final text."""
        from agent.llm.base import ToolUseEvent, TextDelta, ResponseComplete, UsageInfo

        llm = FakeLLMProvider()
        # First call: LLM uses read tool
        llm.responses.append([
            ToolUseEvent(id="tu_001", name="read", input={"path": "src/main.py"}),
            ResponseComplete(
                usage=UsageInfo(input_tokens=100, output_tokens=50),
                stop_reason="tool_use",
            ),
        ])
        # Second call: LLM returns plan text
        llm.responses.append([
            TextDelta(text="Based on reading main.py, here is the plan."),
            ResponseComplete(
                usage=UsageInfo(input_tokens=200, output_tokens=100),
                stop_reason="end_turn",
            ),
        ])

        cli = FakeCLI()
        registry = _build_registry(FakeReadTool())

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        result = await tool.execute(task="Analyze the codebase")

        assert "Based on reading main.py" in result
        # Tool use should have been shown in CLI
        assert len(cli.tool_uses) == 1
        assert cli.tool_uses[0][0] == "read"
        # Tool result should have been shown
        assert len(cli.tool_results) == 1
        assert "contents of src/main.py" in cli.tool_results[0][1]

    async def test_name_and_schema(self, test_config: Config):
        llm = FakeLLMProvider()
        cli = FakeCLI()
        registry = _build_registry()

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)

        assert tool.name == "plan"
        assert "task" in tool.input_schema["properties"]
        assert "task" in tool.input_schema["required"]

    async def test_persists_plan_to_file(self, test_config: Config, tmp_path):
        """Plan output should be saved to the plan file when set."""
        from pathlib import Path

        llm = FakeLLMProvider()
        llm.set_text_response("## Plan\n1. Step one\n2. Step two")
        cli = FakeCLI()
        registry = _build_registry(FakeReadTool())

        plan_file = tmp_path / ".agent" / "plans" / "test-session.md"
        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        tool.set_plan_file(plan_file)

        result = await tool.execute(task="Plan something")

        assert plan_file.exists()
        saved = plan_file.read_text()
        assert "Step one" in saved
        assert saved == result

    async def test_no_persist_without_plan_file(self, test_config: Config, tmp_path):
        """When no plan file is set, execute still works but nothing is saved."""
        llm = FakeLLMProvider()
        llm.set_text_response("A plan.")
        cli = FakeCLI()
        registry = _build_registry()

        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        result = await tool.execute(task="Plan something")

        assert result == "A plan."
        # No plan file should have been created anywhere
        plans_dir = tmp_path / ".agent" / "plans"
        assert not plans_dir.exists()

    async def test_overwrites_previous_plan(self, test_config: Config, tmp_path):
        """Running the plan tool again should overwrite the previous plan."""
        llm = FakeLLMProvider()
        llm.set_text_response("Plan v1")
        cli = FakeCLI()
        registry = _build_registry()

        plan_file = tmp_path / ".agent" / "plans" / "session.md"
        tool = PlanTool(llm=llm, parent_registry=registry, config=test_config, cli=cli)
        tool.set_plan_file(plan_file)

        await tool.execute(task="First plan")
        assert "Plan v1" in plan_file.read_text()

        llm.set_text_response("Plan v2 - revised")
        await tool.execute(task="Revised plan")
        assert "Plan v2 - revised" in plan_file.read_text()
        assert "Plan v1" not in plan_file.read_text()


# ===========================================================================
# Plan persistence in AgentLoop
# ===========================================================================


@pytest.mark.integration
class TestPlanPersistenceInLoop:
    """Test that AgentLoop injects persisted plan into system prompt."""

    async def test_plan_injected_into_system_prompt(self, fake_llm, fake_cli, test_config, tmp_path):
        from tests.integration.conftest import build_agent

        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        # Manually write a plan file with checkbox format
        plan_file = agent._plan_file_for_session()
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text("## Plan\n- [x] Step 1: Do X\n- [ ] Step 2: Do Y")

        system = await agent._build_system_prompt()
        assert "Active Plan" in system
        assert "- [x] Step 1: Do X" in system
        assert "- [ ] Step 2: Do Y" in system
        assert str(plan_file) in system
        assert "edit" in system

    async def test_plan_prompt_mentions_unchecked_steps(self, fake_llm, fake_cli, test_config, tmp_path):
        """System prompt should instruct agent to work through unchecked steps."""
        from tests.integration.conftest import build_agent

        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        plan_file = agent._plan_file_for_session()
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text("## Plan\n- [x] Done step\n- [ ] Pending step")

        system = await agent._build_system_prompt()
        assert "unchecked" in system.lower() or "- [ ]" in system
        assert "- [x]" in system

    async def test_no_plan_no_injection(self, fake_llm, fake_cli, test_config, tmp_path):
        from tests.integration.conftest import build_agent

        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        system = await agent._build_system_prompt()
        assert "Active Plan" not in system

    async def test_plan_tool_wired_to_session(self, fake_llm, fake_cli, test_config, tmp_path):
        """When plan_tool is passed to AgentLoop, it gets the session's plan file."""
        from agent.core.loop import AgentLoop
        from agent.tools.registry import ToolRegistry
        from agent.tools.executor import ToolExecutor

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        plan_tool = PlanTool(
            llm=fake_llm, parent_registry=registry, config=test_config, cli=fake_cli,
        )

        agent = AgentLoop(
            config=test_config, llm=fake_llm, cli=fake_cli,
            project_dir=tmp_path, tool_registry=registry, tool_executor=executor,
            plan_tool=plan_tool,
        )

        expected_path = tmp_path / ".agent" / "plans" / f"{agent._session_id}.md"
        assert plan_tool._plan_file == expected_path


# ===========================================================================
# SubagentRunner with CLI
# ===========================================================================


@pytest.mark.integration
class TestSubagentRunnerWithCLI:
    """Test that SubagentRunner properly streams to CLI when provided."""

    async def test_cli_receives_text_deltas(self, test_config: Config):
        llm = FakeLLMProvider()
        llm.set_text_response("Hello from subagent")
        cli = FakeCLI()
        registry = _build_registry(EchoTool())
        executor = ToolExecutor(registry)

        runner = SubagentRunner(
            llm=llm, tool_registry=registry, tool_executor=executor,
            config=test_config, system_prompt="You are a helper.", cli=cli,
        )
        result = await runner.run("Say hello")

        assert result == "Hello from subagent"
        assert "Hello from subagent" in "".join(cli.output)

    async def test_cli_receives_tool_events(self, test_config: Config):
        from agent.llm.base import ToolUseEvent, TextDelta, ResponseComplete, UsageInfo

        llm = FakeLLMProvider()
        llm.responses.append([
            ToolUseEvent(id="tu_001", name="echo", input={"text": "ping"}),
            ResponseComplete(
                usage=UsageInfo(input_tokens=50, output_tokens=25),
                stop_reason="tool_use",
            ),
        ])
        llm.responses.append([
            TextDelta(text="Done."),
            ResponseComplete(
                usage=UsageInfo(input_tokens=100, output_tokens=50),
                stop_reason="end_turn",
            ),
        ])

        cli = FakeCLI()
        registry = _build_registry(EchoTool())
        executor = ToolExecutor(registry)

        runner = SubagentRunner(
            llm=llm, tool_registry=registry, tool_executor=executor,
            config=test_config, system_prompt="You are a helper.", cli=cli,
        )
        result = await runner.run("Use echo")

        assert result == "Done."
        assert len(cli.tool_uses) == 1
        assert cli.tool_uses[0][0] == "echo"
        assert len(cli.tool_results) == 1
        assert "echo: ping" in cli.tool_results[0][1]

    async def test_cli_none_still_works(self, test_config: Config):
        """Existing silent behavior is preserved when cli=None."""
        llm = FakeLLMProvider()
        llm.set_text_response("Silent response")
        registry = _build_registry(EchoTool())
        executor = ToolExecutor(registry)

        runner = SubagentRunner(
            llm=llm, tool_registry=registry, tool_executor=executor,
            config=test_config, system_prompt="You are a helper.",
        )
        result = await runner.run("Test")

        assert result == "Silent response"


# ===========================================================================
# ToolRegistry.clone_including
# ===========================================================================


@pytest.mark.integration
class TestCloneIncluding:
    def test_includes_only_specified_tools(self):
        echo = EchoTool()
        read = FakeReadTool()
        reg = _build_registry(echo, read)

        cloned = reg.clone_including({"read"})

        assert "read" in cloned.list_names()
        assert "echo" not in cloned.list_names()

    def test_empty_inclusion_gives_empty(self):
        reg = _build_registry(EchoTool(), FakeReadTool())
        cloned = reg.clone_including(set())
        assert cloned.list_names() == []

    def test_include_all(self):
        reg = _build_registry(EchoTool(), FakeReadTool())
        cloned = reg.clone_including({"echo", "read"})
        assert set(cloned.list_names()) == {"echo", "read"}

    def test_original_unchanged(self):
        reg = _build_registry(EchoTool(), FakeReadTool())
        reg.clone_including({"echo"})
        assert set(reg.list_names()) == {"echo", "read"}
