"""Subagent tool for task delegation with sync and async execution."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Coroutine

from agent.config import Config
from agent.llm.base import LLMProvider
from agent.subagent.runner import SubagentRunner
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Tools excluded from subagent registries.
_EXCLUDED_TOOLS = frozenset({
    "subagent",      # prevent recursive spawning
    "memory_save",   # prevent memory modification
    "ask_user",      # subagents run non-interactively
    "update_plan",   # plan is session-scoped
})


class SubagentManager:
    """Tracks async subagent tasks and their results."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[str]] = {}
        self._counter: int = 0

    def launch(self, coro: Coroutine[Any, Any, str]) -> str:
        """Wrap a coroutine in an asyncio.Task and return a task_id."""
        self._counter += 1
        task_id = f"subagent-{self._counter}"
        self._tasks[task_id] = asyncio.create_task(coro, name=task_id)
        return task_id

    def get_result(self, task_id: str) -> str:
        """Return the result if done, a status string otherwise."""
        task = self._tasks.get(task_id)
        if task is None:
            return f"Unknown task_id: {task_id}"
        if not task.done():
            return "Status: running"
        exc = task.exception()
        if exc is not None:
            return f"Status: failed\nError: {exc}"
        return f"Status: completed\nResult:\n{task.result()}"

    def list_tasks(self) -> list[dict[str, str]]:
        """Return a summary of all tracked tasks."""
        items: list[dict[str, str]] = []
        for task_id, task in self._tasks.items():
            if not task.done():
                status = "running"
            elif task.exception() is not None:
                status = "failed"
            else:
                status = "completed"
            items.append({"task_id": task_id, "status": status})
        return items


class SubagentTool:
    """Allows the main agent to delegate tasks to independent subagents.

    Supports four actions:
      - run:    synchronous execution (blocks until done)
      - launch: asynchronous execution (returns task_id immediately)
      - check:  retrieve the result of an async subagent
      - list:   show all tracked async subagents and their statuses
    """

    def __init__(
        self,
        llm: LLMProvider,
        parent_registry: ToolRegistry,
        config: Config,
        default_system_prompt: str,
    ) -> None:
        self._llm = llm
        self._parent_registry = parent_registry
        self._config = config
        self._default_system_prompt = default_system_prompt
        self._manager = SubagentManager()

    @property
    def name(self) -> str:
        return "subagent"

    @property
    def description(self) -> str:
        return (
            "Delegate a task to an independent subagent. The subagent has its own "
            "conversation and access to all tools (except subagent, memory_save, "
            "ask_user). Supports synchronous ('run') and asynchronous ('launch'/"
            "'check'/'list') execution."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["run", "launch", "check", "list"],
                    "description": (
                        "'run' executes synchronously and returns the result. "
                        "'launch' starts an async subagent and returns a task_id. "
                        "'check' retrieves the result of an async subagent by task_id. "
                        "'list' shows all tracked async subagents."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "The task description for the subagent. "
                        "Required for 'run' and 'launch' actions."
                    ),
                },
                "system_prompt": {
                    "type": "string",
                    "description": (
                        "Optional custom system prompt for the subagent. "
                        "If omitted, the default agent system prompt is used."
                    ),
                },
                "task_id": {
                    "type": "string",
                    "description": (
                        "The task_id to check. Required for 'check' action."
                    ),
                },
            },
            "required": ["action"],
        }

    async def execute(self, **params: Any) -> str:
        action = params.get("action", "")
        task = params.get("task", "")
        system_prompt = params.get("system_prompt", "") or self._build_system_prompt()
        task_id = params.get("task_id", "")

        if action == "run":
            if not task:
                return "Error: 'task' is required for 'run' action."
            runner = self._create_runner(system_prompt)
            return await runner.run(task)

        elif action == "launch":
            if not task:
                return "Error: 'task' is required for 'launch' action."
            runner = self._create_runner(system_prompt)
            tid = self._manager.launch(runner.run(task))
            return f"Subagent launched with task_id: {tid}"

        elif action == "check":
            if not task_id:
                return "Error: 'task_id' is required for 'check' action."
            return self._manager.get_result(task_id)

        elif action == "list":
            tasks = self._manager.list_tasks()
            if not tasks:
                return "No subagents have been launched."
            return json.dumps(tasks, indent=2)

        return f"Error: Unknown action '{action}'. Use 'run', 'launch', 'check', or 'list'."

    def _build_system_prompt(self) -> str:
        """Build the default system prompt with dynamic placeholders filled."""
        prompt = self._default_system_prompt
        prompt = prompt.replace("{{CWD}}", str(Path.cwd()))
        prompt = prompt.replace("{{LOCAL_TIME}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return prompt

    def _create_runner(self, system_prompt: str) -> SubagentRunner:
        """Create a SubagentRunner with a filtered tool registry."""
        child_registry = self._parent_registry.clone_excluding(_EXCLUDED_TOOLS)
        child_executor = ToolExecutor(child_registry)
        return SubagentRunner(
            llm=self._llm,
            tool_registry=child_registry,
            tool_executor=child_executor,
            config=self._config,
            system_prompt=system_prompt,
        )
