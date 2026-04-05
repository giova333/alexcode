"""Plan tool: delegates planning tasks to a read-only subagent with console output."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.config import Config
from agent.llm.base import LLMProvider
from agent.subagent.runner import SubagentRunner
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agent.cli import CLI

logger = logging.getLogger(__name__)

_PLAN_TOOLS = frozenset({
    "read",
    "glob",
    "grep",
    "bash",
    "web_fetch",
    "web_search",
})

_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "prompts"


def _load_plan_prompt() -> str:
    """Load the bundled PLAN.md prompt."""
    path = _PROMPTS_DIR / "PLAN.md"
    return path.read_text().strip()


class PlanTool:
    """Delegates planning tasks to a read-only subagent that streams output to the console.

    The plan agent explores the codebase using only read-only tools and produces
    an implementation plan. Unlike the general subagent, it cannot modify files,
    save memories, or spawn other agents.
    """

    def __init__(
        self,
        llm: LLMProvider,
        parent_registry: ToolRegistry,
        config: Config,
        cli: CLI,
    ) -> None:
        self._llm = llm
        self._parent_registry = parent_registry
        self._config = config
        self._cli = cli
        self._plan_file: Path | None = None

    def set_plan_file(self, path: Path) -> None:
        """Set the file path where plan output will be persisted."""
        self._plan_file = path

    @property
    def name(self) -> str:
        return "plan"

    @property
    def description(self) -> str:
        return (
            "Delegate a planning task to a specialized read-only agent. "
            "The plan agent explores the codebase using read-only tools "
            "(read, glob, grep, bash, web_fetch, web_search) and produces "
            "a detailed implementation plan. Output is streamed to the console."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The planning task. Describe what you need the plan agent to "
                        "explore, analyze, and design. The plan agent will explore the "
                        "codebase using read-only tools and produce an implementation plan."
                    ),
                },
            },
            "required": ["task"],
        }

    async def execute(self, **params: Any) -> str:
        task = params.get("task", "")
        if not task:
            return "Error: 'task' is required."
        runner = self._create_runner()
        result = await runner.run(task)
        self._persist_plan(result)
        return result

    def _persist_plan(self, plan_text: str) -> None:
        """Save plan output to disk so it survives across sessions."""
        if not self._plan_file or not plan_text:
            return
        try:
            self._plan_file.parent.mkdir(parents=True, exist_ok=True)
            self._plan_file.write_text(plan_text)
        except OSError:
            logger.warning("Failed to persist plan to %s", self._plan_file)

    def _build_system_prompt(self) -> str:
        """Build the plan system prompt with dynamic placeholders filled."""
        prompt = _load_plan_prompt()
        prompt = prompt.replace("{{CWD}}", str(Path.cwd()))
        prompt = prompt.replace("{{LOCAL_TIME}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return prompt

    def _create_runner(self) -> SubagentRunner:
        """Create a SubagentRunner with only read-only tools and CLI streaming."""
        # Build allowlist: plan tools + any MCP tools from parent registry
        allowed = set(_PLAN_TOOLS)
        for name in self._parent_registry.list_names():
            if name.startswith("mcp__"):
                allowed.add(name)
        child_registry = self._parent_registry.clone_including(allowed)
        child_executor = ToolExecutor(child_registry)
        return SubagentRunner(
            llm=self._llm,
            tool_registry=child_registry,
            tool_executor=child_executor,
            config=self._config,
            system_prompt=self._build_system_prompt(),
            cli=self._cli,
        )
