"""Main agent loop: user -> LLM -> tools -> LLM -> ... -> text response."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.cli import CLI
from agent.compaction.compactor import Compactor
from agent.config import Config
from agent.core.conversation import Conversation
from agent.core.message import Message
from agent.core.tokens import count_message_tokens
from agent.history.storage import HistoryStorage
from agent.llm.base import LLMProvider, TextDelta, ThinkingDelta, ToolUseEvent, ResponseComplete
from agent.memory.manager import MemoryManager
from agent.skills.loader import SkillLoader
from agent.skills.skill import Skill
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Shortcuts for /model command — maps aliases to full model IDs
MODEL_ALIASES: dict[str, str] = {
    # Current generation
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    # Previous generations
    "sonnet-4.5": "claude-sonnet-4-5-20250929",
    "opus-4.5": "claude-opus-4-5-20251101",
    "opus-4.1": "claude-opus-4-1-20250805",
    "sonnet-4": "claude-sonnet-4-20250514",
    "opus-4": "claude-opus-4-20250514",
}

_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"


def _load_system_prompt() -> str:
    """Load the bundled SYSTEM.md prompt. Always required."""
    path = _PROMPTS_DIR / "SYSTEM.md"
    return path.read_text().strip()


class AgentLoop:
    """Orchestrates the conversation between user, LLM, and tools."""

    def __init__(
        self,
        config: Config,
        llm: LLMProvider,
        cli: CLI,
        project_dir: Path,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        memory_manager: MemoryManager | None = None,
        history: HistoryStorage | None = None,
        skill_loader: SkillLoader | None = None,
        skills: list[Skill] | None = None,
    ) -> None:
        self._config = config
        self._llm = llm
        self._cli = cli
        self._project_dir = project_dir
        self._conversation = Conversation()
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._memory_manager = memory_manager
        self._history = history
        self._session_id = history.new_session_id() if history else ""
        self._skill_loader = skill_loader
        self._skills = skills or []
        self._compactor = Compactor(
            config.compaction,
            llm,
            memory_manager,
            self._conversation,
        )

    def resume_session(self, session_id: str) -> bool:
        """Load a previous session into the conversation. Returns True on success."""
        if not self._history:
            return False
        messages = self._history.load(session_id)
        if not messages:
            return False
        self._conversation.load_messages(messages)
        self._session_id = session_id
        return True

    async def run(self) -> None:
        """Main loop: read input, get response, repeat."""
        self._cli.print_welcome(self._config.provider, self._config.model)

        if self._skills:
            invocable = [s for s in self._skills if s.user_invocable]
            if invocable:
                self._cli.print_info(f"Skills: {', '.join('/' + s.name for s in invocable)}")

        while True:
            user_input = await self._cli.get_input()
            if user_input is None:
                self._save_history()
                self._cli.print_info("Goodbye!")
                break

            # Handle built-in commands and skill invocations
            if user_input.startswith("/"):
                try:
                    if await self._handle_command(user_input):
                        continue
                except KeyboardInterrupt:
                    self._cli.print_info("Interrupted.")
                    continue
                except Exception as e:
                    logger.exception("Error handling command")
                    self._cli.print_error(f"Error: {e}")
                    continue

            try:
                await self._process_message(user_input)
            except KeyboardInterrupt:
                self._cli.print_info("Interrupted.")
            except Exception as e:
                logger.exception("Error processing message")
                self._cli.print_error(f"Error: {e}")
                self._save_history()

    async def _handle_command(self, command: str) -> bool:
        """Handle slash commands. Returns True if handled."""
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            self._save_history()
            raise SystemExit(0)
        elif cmd == "/clear":
            self._conversation.clear()
            if self._history:
                self._history.clear_session(self._session_id)
                self._session_id = self._history.new_session_id()
            self._cli.print_info("Conversation cleared.")
            return True
        elif cmd == "/history":
            for msg in self._conversation.messages:
                role = msg.role
                text = msg.text[:100] if msg.text else "(tool interaction)"
                self._cli.print_info(f"  [{role}] {text}")
            return True
        elif cmd == "/tokens":
            self._cli.print_info(f"Total tokens: {self._conversation.total_tokens:,}")
            return True
        elif cmd == "/tools":
            if self._tool_registry:
                for name in self._tool_registry.list_names():
                    self._cli.print_info(f"  {name}")
            return True
        elif cmd == "/sessions":
            if self._history:
                for s in self._history.list_sessions():
                    self._cli.print_info(
                        f"  {s['session_id']} ({s['message_count']} messages) — {s['timestamp']}"
                    )
            return True
        elif cmd == "/resume":
            if not self._history:
                self._cli.print_error("History storage not configured.")
                return True
            if arg:
                session_id = self._history.find_session(arg)
            else:
                session_id = self._history.get_latest_session_id()
            if not session_id:
                self._cli.print_error("Session not found." if arg else "No previous sessions.")
                return True
            # Save current session before switching
            self._save_history()
            if self.resume_session(session_id):
                msg_count = len(self._conversation.messages)
                self._cli.print_info(f"Resumed session: {session_id} ({msg_count} messages, {self._conversation.total_tokens:,} tokens)")
                # Show last few messages as context
                recent = [m for m in self._conversation.messages if m.text][-3:]
                for m in recent:
                    preview = m.text[:120] + "..." if len(m.text) > 120 else m.text
                    self._cli.print_info(f"  [{m.role}] {preview}")
            else:
                self._cli.print_error(f"Failed to load session: {session_id}")
            return True
        elif cmd == "/compact":
            compacted = await self._compactor.maybe_compact()
            if compacted:
                self._cli.print_compaction_notice()
                if self._history:
                    self._history.rewrite(self._session_id, self._conversation.messages)
                self._cli.print_info(f"Compacted. Tokens: {self._conversation.total_tokens:,}")
            else:
                self._cli.print_info(f"No compaction needed. Tokens: {self._conversation.total_tokens:,}")
            return True
        elif cmd == "/skills":
            invocable = [s for s in self._skills if s.user_invocable]
            model_only = [s for s in self._skills if not s.user_invocable and not s.disable_model_invocation]
            if invocable:
                self._cli.print_info("  User-invocable skills:")
                for s in invocable:
                    hint = f" {s.argument_hint}" if s.argument_hint else ""
                    self._cli.print_info(f"    /{s.name}{hint} — {s.description}")
            if model_only:
                self._cli.print_info("  Background skills (auto-activated by LLM):")
                for s in model_only:
                    self._cli.print_info(f"    {s.name} — {s.description}")
            if not invocable and not model_only:
                self._cli.print_info("  No skills loaded.")
            return True
        elif cmd == "/model":
            if not arg:
                aliases = ", ".join(f"{k}" for k in MODEL_ALIASES)
                self._cli.print_info(f"Current model: {self._config.model}")
                self._cli.print_info(f"Usage: /model <name>")
                self._cli.print_info(f"Shortcuts: {aliases}")
                return True
            new_model = MODEL_ALIASES.get(arg.lower(), arg)
            self._config.model = new_model
            self._llm._model = new_model
            self._cli.print_info(f"Switched to model: {new_model}")
            return True
        elif cmd == "/prompt":
            system = await self._build_system_prompt()
            self._cli.print_assistant_text(f"```\n{system}\n```")
            return True
        elif cmd == "/help":
            self._cli.print_info("Commands: /exit /clear /history /tokens /tools /sessions /resume [id] /compact /skills /model /prompt /help")
            invocable = [s for s in self._skills if s.user_invocable]
            if invocable:
                self._cli.print_info(f"Skills: {', '.join('/' + s.name for s in invocable)}")
            return True
        else:
            # Check if it's a skill invocation: /skill-name [args]
            skill_name = cmd[1:]  # strip leading /
            if self._skill_loader:
                skill = self._skill_loader.get_by_name(skill_name, self._skills)
                if skill and skill.user_invocable:
                    await self._invoke_skill(skill, arg)
                    return True
        return False

    async def _invoke_skill(self, skill: Skill, arguments: str) -> None:
        """Invoke a skill: load its full body, render with arguments, send as user message."""
        rendered = skill.render(arguments)
        if not rendered:
            self._cli.print_error(f"Skill '{skill.name}' has no instructions.")
            return

        self._cli.print_info(f"Running skill: {skill.name}")
        # The rendered skill prompt becomes the user message
        await self._process_message(rendered)

    def _expand_file_references(self, text: str) -> str:
        """Expand @path references by inlining file contents."""
        pattern = re.compile(r"(?:^|(?<=\s))@(\S+)")
        matches = list(pattern.finditer(text))
        if not matches:
            return text

        attachments: list[str] = []
        for match in matches:
            ref = match.group(1)
            path = self._project_dir / ref
            try:
                if path.is_file():
                    content = path.read_text(errors="replace")
                    # Limit to ~50KB to avoid token explosion
                    if len(content) > 50_000:
                        content = content[:50_000] + "\n... (truncated)"
                    attachments.append(f"<file path=\"{ref}\">\n{content}\n</file>")
                elif path.is_dir():
                    entries = sorted(path.iterdir())
                    listing = "\n".join(
                        f"  {'[dir] ' if e.is_dir() else ''}{e.name}"
                        for e in entries
                        if not e.name.startswith(".")
                    )
                    attachments.append(f"<directory path=\"{ref}\">\n{listing}\n</directory>")
            except (OSError, PermissionError):
                continue

        if attachments:
            return text + "\n\n" + "\n\n".join(attachments)
        return text

    async def _process_message(self, user_input: str) -> None:
        """Process a user message through the full LLM cycle."""
        user_input = self._expand_file_references(user_input)
        user_msg = Message.user(user_input)
        user_msg.token_count = count_message_tokens(user_msg.to_dict())
        self._conversation.append(user_msg)

        # Check compaction before calling LLM
        if await self._compactor.maybe_compact():
            self._cli.print_compaction_notice()
            # Rewrite history file since conversation was replaced with summary
            if self._history:
                self._history.rewrite(self._session_id, self._conversation.messages)

        await self._run_llm_cycle()
        self._save_history()

    async def _run_llm_cycle(self) -> None:
        """Call LLM, handle tool use, repeat until text response."""
        while True:
            system = await self._build_system_prompt()
            tools = self._get_tool_definitions()

            text_parts: list[str] = []
            tool_uses: list[ToolUseEvent] = []
            usage_info = None
            is_thinking = False

            reasoning_cfg = self._config.reasoning if self._config.reasoning.enabled else None

            self._cli.start_response()

            async for event in self._llm.stream(
                system=system,
                messages=self._conversation.to_api_messages(),
                tools=tools if tools else None,
                max_tokens=self._config.max_tokens,
                reasoning=reasoning_cfg,
            ):
                if isinstance(event, ThinkingDelta):
                    if not is_thinking:
                        is_thinking = True
                        self._cli.start_thinking()
                    if self._config.reasoning.show_thinking:
                        self._cli.print_thinking_delta(event.text)
                elif isinstance(event, TextDelta):
                    if is_thinking:
                        is_thinking = False
                        self._cli.end_thinking()
                    text_parts.append(event.text)
                    self._cli.print_text_delta(event.text)
                elif isinstance(event, ToolUseEvent):
                    if is_thinking:
                        is_thinking = False
                        self._cli.end_thinking()
                    tool_uses.append(event)
                elif isinstance(event, ResponseComplete):
                    if is_thinking:
                        is_thinking = False
                        self._cli.end_thinking()
                    usage_info = event

            self._cli.end_response()

            # Build assistant message
            content_blocks: list[dict[str, Any]] = []
            full_text = "".join(text_parts)
            if full_text:
                content_blocks.append({"type": "text", "text": full_text})
            for tu in tool_uses:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tu.id,
                    "name": tu.name,
                    "input": tu.input,
                })

            if content_blocks:
                assistant_msg = Message(role="assistant", content=content_blocks)
                if usage_info:
                    assistant_msg.token_count = usage_info.usage.input_tokens + usage_info.usage.output_tokens
                self._conversation.append(assistant_msg)

            if usage_info:
                self._cli.print_usage(usage_info.usage.input_tokens, usage_info.usage.output_tokens)

            if not tool_uses:
                return

            # Execute tools — always produce a tool_result for every tool_use
            # to keep the conversation valid for the Anthropic API.
            tool_result_blocks: list[dict[str, Any]] = []
            for tu in tool_uses:
                try:
                    self._cli.print_tool_use(tu.name, tu.input)
                    result_text, is_error = await self._execute_tool(tu.name, tu.input)
                    self._cli.print_tool_result(tu.name, result_text, is_error)
                except Exception as e:
                    result_text = f"Internal error during tool execution: {e}"
                    is_error = True
                    self._cli.print_tool_result(tu.name, result_text, is_error)
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                    "is_error": is_error,
                })

            result_msg = Message(role="user", content=tool_result_blocks)
            result_msg.token_count = count_message_tokens(result_msg.to_dict())
            self._conversation.append(result_msg)

    async def _execute_tool(self, name: str, input_data: dict) -> tuple[str, bool]:
        if self._tool_executor is None:
            return f"Tool '{name}' not available (no tools registered).", True
        try:
            result = await self._tool_executor.execute(name, input_data)
            return result, False
        except Exception as e:
            return f"Error executing {name}: {e}", True

    def _load_agents_md(self) -> str:
        """Load AGENTS.md from .agent/AGENTS.md and project root (both merged)."""
        parts = []
        for candidate in [
            self._project_dir / ".agent" / "AGENTS.md",
            self._project_dir / "AGENTS.md",
        ]:
            if candidate.exists():
                content = candidate.read_text().strip()
                if content:
                    parts.append(content)
        return "\n\n".join(parts)

    async def _build_system_prompt(self) -> str:
        system = _load_system_prompt()
        # Inject dynamic context into placeholders
        system = system.replace("{{CWD}}", str(Path.cwd()))
        system = system.replace("{{LOCAL_TIME}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        parts = [system]

        # AGENTS.md instructions
        agents_md = self._load_agents_md()
        if agents_md:
            parts.append(f"\n# Project Instructions (AGENTS.md)\n{agents_md}")

        # Memory context
        if self._memory_manager:
            try:
                memory_context = await self._memory_manager.load_context()
                if memory_context:
                    parts.append(f"\n# Memory\n{memory_context}")
            except Exception:
                pass

        # Skill metadata for LLM discovery (only name + description, not full body)
        if self._skill_loader:
            model_skills = self._skill_loader.get_model_available(self._skills)
            if model_skills:
                parts.append("\n# Available Skills")
                parts.append("The following skills can be suggested to the user via slash commands (e.g., /skill-name).")
                for skill in model_skills:
                    desc = f": {skill.description}" if skill.description else ""
                    parts.append(f"- {skill.name}{desc}")

        return "\n".join(parts)

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        if self._tool_registry is None:
            return []
        return self._tool_registry.all_definitions()

    def _save_history(self) -> None:
        if self._history and self._conversation.messages:
            self._history.save(self._session_id, self._conversation.messages)

            # Index this session for future memory search
            if self._memory_manager:
                try:
                    text_parts = []
                    for msg in self._conversation.messages:
                        if msg.text:
                            text_parts.append(f"[{msg.role}]: {msg.text}")
                        elif isinstance(msg.content, list):
                            for block in msg.content:
                                if block.get("type") == "tool_use":
                                    text_parts.append(f"[assistant]: Called {block['name']}")
                                elif block.get("type") == "tool_result":
                                    preview = str(block.get("content", ""))[:500]
                                    text_parts.append(f"[tool_result]: {preview}")
                    if text_parts:
                        self._memory_manager.index_session(
                            "\n\n".join(text_parts), self._session_id
                        )
                except Exception:
                    pass  # indexing is best-effort
