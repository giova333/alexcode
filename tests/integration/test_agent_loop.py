"""Integration tests for the core agent loop: message processing, tool use round-trips, commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.core.loop import AgentLoop
from agent.core.message import Message
from agent.llm.base import TextDelta, ThinkingDelta, ToolUseEvent, ResponseComplete, UsageInfo
from agent.tools.base import Tool
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry

from tests.integration.conftest import build_agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class EchoTool:
    """A trivial tool that echoes its input — useful for testing tool round-trips."""

    name = "echo"
    description = "Echoes the input back."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, **params) -> str:
        return f"echo: {params.get('text', '')}"


class FailTool:
    """A tool that always raises — tests error handling."""

    name = "fail"
    description = "Always fails."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, **params) -> str:
        raise RuntimeError("intentional failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestBasicWorkflow:
    """User sends a message, LLM replies with text."""

    async def test_simple_text_response(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_text_response("Hello, world!")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("Hi there")

        # Conversation should have user + assistant messages
        msgs = agent._conversation.messages
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].text == "Hi there"
        assert msgs[1].role == "assistant"
        assert msgs[1].text == "Hello, world!"

    async def test_llm_receives_user_message(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_text_response("ok")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("test input")

        assert len(fake_llm.calls) == 1
        api_messages = fake_llm.calls[0]["messages"]
        assert api_messages[-1]["role"] == "user"
        content = api_messages[-1]["content"]
        assert any(b.get("text") == "test input" for b in content)

    async def test_multi_turn_conversation(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_text_response("Reply 1")
        fake_llm.set_text_response("Reply 2")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("First message")
        await agent._process_message("Second message")

        msgs = agent._conversation.messages
        assert len(msgs) == 4
        assert msgs[0].text == "First message"
        assert msgs[1].text == "Reply 1"
        assert msgs[2].text == "Second message"
        assert msgs[3].text == "Reply 2"

    async def test_total_tokens_synced_from_api(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_text_response("ok", input_tokens=5000, output_tokens=100)
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("hello")

        assert agent._conversation.total_tokens == 5000


@pytest.mark.integration
class TestToolUseRoundTrip:
    """LLM requests a tool call, agent executes it and feeds result back."""

    async def test_tool_call_and_result(self, fake_llm, fake_cli, test_config, tmp_path):
        echo = EchoTool()
        fake_llm.set_tool_then_text("echo", {"text": "ping"}, final_text="Got the echo.")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path, extra_tools=[echo])

        await agent._process_message("Use the echo tool")

        # Should have: user, assistant(tool_use), user(tool_result), assistant(text)
        msgs = agent._conversation.messages
        assert len(msgs) == 4
        assert msgs[1].content[0]["type"] == "tool_use"
        assert msgs[2].content[0]["type"] == "tool_result"
        assert msgs[2].content[0]["content"] == "echo: ping"
        assert msgs[3].text == "Got the echo."

    async def test_tool_error_handling(self, fake_llm, fake_cli, test_config, tmp_path):
        fail = FailTool()
        fake_llm.set_tool_then_text("fail", {}, final_text="Handled error.")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path, extra_tools=[fail])

        await agent._process_message("Call the fail tool")

        msgs = agent._conversation.messages
        tool_result = msgs[2].content[0]
        assert tool_result["is_error"] is True
        assert "intentional failure" in tool_result["content"]

    async def test_unknown_tool_returns_error(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.responses.append([
            ToolUseEvent(id="t1", name="nonexistent", input={}),
            ResponseComplete(usage=UsageInfo(input_tokens=50, output_tokens=20), stop_reason="tool_use"),
        ])
        fake_llm.set_text_response("ok")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("call nonexistent")

        msgs = agent._conversation.messages
        tool_result = msgs[2].content[0]
        assert tool_result["is_error"] is True
        assert "nonexistent" in tool_result["content"]

    async def test_cli_receives_tool_events(self, fake_llm, fake_cli, test_config, tmp_path):
        echo = EchoTool()
        fake_llm.set_tool_then_text("echo", {"text": "hi"}, final_text="Done")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path, extra_tools=[echo])

        await agent._process_message("echo something")

        assert ("echo", {"text": "hi"}) in fake_cli.tool_uses
        assert any(name == "echo" and not is_err for name, _, is_err in fake_cli.tool_results)

    async def test_multiple_concurrent_tool_calls(self, fake_llm, fake_cli, test_config, tmp_path):
        """LLM returns two tool calls in a single response."""
        echo = EchoTool()
        fake_llm.set_multi_tool_response([
            ("t1", "echo", {"text": "first"}),
            ("t2", "echo", {"text": "second"}),
        ], final_text="Both done.")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path, extra_tools=[echo])

        await agent._process_message("call echo twice")

        msgs = agent._conversation.messages
        # user, assistant(2 tool_uses), user(2 tool_results), assistant(text)
        assert len(msgs) == 4
        # Assistant message has two tool_use blocks
        tool_use_blocks = [b for b in msgs[1].content if b.get("type") == "tool_use"]
        assert len(tool_use_blocks) == 2
        # Tool result message has two results
        tool_result_blocks = msgs[2].content
        assert len(tool_result_blocks) == 2
        assert all(b["type"] == "tool_result" for b in tool_result_blocks)
        assert tool_result_blocks[0]["tool_use_id"] == "t1"
        assert tool_result_blocks[1]["tool_use_id"] == "t2"
        assert "echo: first" in tool_result_blocks[0]["content"]
        assert "echo: second" in tool_result_blocks[1]["content"]
        assert msgs[3].text == "Both done."


@pytest.mark.integration
class TestThinkingMode:
    """Extended thinking / reasoning mode handling."""

    async def test_thinking_events_forwarded_to_cli(self, fake_llm, fake_cli, test_config, tmp_path):
        test_config.reasoning.enabled = True
        test_config.reasoning.show_thinking = True
        fake_llm.set_thinking_then_text("Let me think...", "The answer is 42.")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("What is the meaning of life?")

        assert any("[thinking] Let me think..." in o for o in fake_cli.output)
        assert any("The answer is 42." in o for o in fake_cli.output)
        assert fake_cli.thinking_started >= 1
        assert fake_cli.thinking_ended >= 1

    async def test_thinking_blocks_preserved_in_message(self, fake_llm, fake_cli, test_config, tmp_path):
        thinking_blocks = [
            {"type": "thinking", "thinking": "deep thought", "signature": "sig_abc"}
        ]
        fake_llm.set_thinking_then_text(
            "deep thought", "answer",
            thinking_blocks=thinking_blocks,
        )
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("think")

        assistant_msg = agent._conversation.messages[1]
        # Thinking blocks should be prepended to content
        assert assistant_msg.content[0]["type"] == "thinking"
        assert assistant_msg.content[0]["signature"] == "sig_abc"
        # Text follows
        text_blocks = [b for b in assistant_msg.content if b.get("type") == "text"]
        assert any("answer" in b["text"] for b in text_blocks)

    async def test_thinking_hidden_when_show_thinking_false(self, fake_llm, fake_cli, test_config, tmp_path):
        test_config.reasoning.enabled = True
        test_config.reasoning.show_thinking = False
        fake_llm.set_thinking_then_text("secret thought", "visible answer")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        await agent._process_message("think quietly")

        # Thinking should NOT appear in CLI output
        assert not any("[thinking]" in o for o in fake_cli.output)
        assert any("visible answer" in o for o in fake_cli.output)


@pytest.mark.integration
class TestLLMErrorHandling:
    """Behavior when the LLM stream raises an exception."""

    async def test_llm_error_mid_stream_propagates(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_error_response(RuntimeError("API connection lost"))
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        # _process_message doesn't catch exceptions itself — run() does.
        # Test that the error propagates correctly.
        with pytest.raises(RuntimeError, match="API connection lost"):
            await agent._process_message("hello")

    async def test_conversation_state_after_error(self, fake_llm, fake_cli, test_config, tmp_path):
        """After an LLM error, the user message should still be in conversation."""
        fake_llm.set_error_response(RuntimeError("network error"))
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        with pytest.raises(RuntimeError):
            await agent._process_message("my question")

        # User message was appended before the LLM call
        assert len(agent._conversation.messages) == 1
        assert agent._conversation.messages[0].text == "my question"


@pytest.mark.integration
class TestCommandHandling:
    """Slash command dispatch."""

    async def test_clear_resets_conversation(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_text_response("hi")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        await agent._process_message("hello")
        assert len(agent._conversation.messages) > 0

        handled = await agent._handle_command("/clear")
        assert handled is True
        assert len(agent._conversation.messages) == 0

    async def test_tokens_command(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_text_response("hi", input_tokens=1234)
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        await agent._process_message("hi")

        handled = await agent._handle_command("/tokens")
        assert handled is True
        assert any("1,234" in o for o in fake_cli.output)

    async def test_history_command(self, fake_llm, fake_cli, test_config, tmp_path):
        fake_llm.set_text_response("response")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        await agent._process_message("message")

        handled = await agent._handle_command("/history")
        assert handled is True
        assert any("[user]" in o for o in fake_cli.output)
        assert any("[assistant]" in o for o in fake_cli.output)

    async def test_help_command(self, fake_llm, fake_cli, test_config, tmp_path):
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        handled = await agent._handle_command("/help")
        assert handled is True
        assert any("Commands:" in o for o in fake_cli.output)

    async def test_unknown_command_returns_false(self, fake_llm, fake_cli, test_config, tmp_path):
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        handled = await agent._handle_command("/nonexistent")
        assert handled is False

    async def test_model_command_switches_model(self, fake_llm, fake_cli, test_config, tmp_path):
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        handled = await agent._handle_command("/model opus")
        assert handled is True
        assert test_config.model == "claude-opus-4-7"
        assert fake_llm._model == "claude-opus-4-7"
        assert any("claude-opus-4-7" in o for o in fake_cli.output)

    async def test_model_command_custom_name(self, fake_llm, fake_cli, test_config, tmp_path):
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        handled = await agent._handle_command("/model my-custom-model")
        assert handled is True
        assert test_config.model == "my-custom-model"

    async def test_model_command_no_arg_shows_current(self, fake_llm, fake_cli, test_config, tmp_path):
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        handled = await agent._handle_command("/model")
        assert handled is True
        assert any("test-model" in o for o in fake_cli.output)


@pytest.mark.integration
class TestSystemPromptConstruction:
    """System prompt includes memory context, skills metadata, and AGENTS.md."""

    async def test_system_prompt_includes_memory(self, fake_llm, fake_cli, test_config, tmp_path, memory_manager):
        await memory_manager.save_main("Project uses PostgreSQL")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path, memory_manager=memory_manager)

        system = await agent._build_system_prompt()
        assert "PostgreSQL" in system
        assert "# Memory" in system

    async def test_system_prompt_includes_agents_md(self, fake_llm, fake_cli, test_config, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("Always use snake_case for variables.")
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)

        system = await agent._build_system_prompt()
        assert "snake_case" in system
        assert "Project Instructions" in system

    async def test_system_prompt_includes_skill_metadata(self, fake_llm, fake_cli, test_config, tmp_path):
        from agent.skills.skill import Skill
        from agent.skills.loader import SkillLoader

        skill = Skill(name="review", description="Review code for bugs")
        loader = SkillLoader(skill_dirs=[], base_dir=tmp_path)
        agent = build_agent(
            fake_llm, fake_cli, test_config, tmp_path,
            skill_loader=loader, skills=[skill],
        )

        system = await agent._build_system_prompt()
        assert "review" in system
        assert "Review code for bugs" in system


@pytest.mark.integration
class TestFileReferences:
    """@path reference expansion."""

    async def test_file_reference_expansion(self, fake_llm, fake_cli, test_config, tmp_path):
        test_file = tmp_path / "hello.txt"
        test_file.write_text("file content here")

        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        expanded = agent._expand_file_references("Check @hello.txt")

        assert "file content here" in expanded
        assert '<file path="hello.txt">' in expanded

    async def test_directory_reference_expansion(self, fake_llm, fake_cli, test_config, tmp_path):
        subdir = tmp_path / "mydir"
        subdir.mkdir()
        (subdir / "a.txt").write_text("a")
        (subdir / "b.txt").write_text("b")

        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        expanded = agent._expand_file_references("List @mydir")

        assert '<directory path="mydir">' in expanded
        assert "a.txt" in expanded
        assert "b.txt" in expanded

    async def test_nonexistent_reference_unchanged(self, fake_llm, fake_cli, test_config, tmp_path):
        agent = build_agent(fake_llm, fake_cli, test_config, tmp_path)
        result = agent._expand_file_references("nothing @nonexistent here")
        assert "@nonexistent" in result


@pytest.mark.integration
class TestMidCycleCompaction:
    """Compaction triggered after tool results push tokens over threshold."""

    async def test_mid_cycle_compaction_triggers(self, fake_llm, fake_cli, test_config, tmp_path, memory_manager):
        # Set low threshold
        test_config.compaction.threshold_tokens = 200
        test_config.compaction.keep_recent_messages = 2

        echo = EchoTool()
        # First call: tool use with high token count
        fake_llm.set_tool_then_text(
            "echo", {"text": "big"}, final_text="Done.",
            input_tokens=300, output_tokens=50,
        )
        # Compaction will need extract + summarize responses
        fake_llm.set_text_response("extracted facts")
        fake_llm.set_text_response("conversation summary")

        agent = build_agent(
            fake_llm, fake_cli, test_config, tmp_path,
            extra_tools=[echo], memory_manager=memory_manager,
        )

        await agent._process_message("Use echo")

        # Compaction notice should have been printed
        assert "[compaction]" in fake_cli.output
