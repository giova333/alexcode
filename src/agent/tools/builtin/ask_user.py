"""AskUser tool: prompt the user for clarification mid-conversation."""

from __future__ import annotations

from typing import Any

from agent.cli import CLI


class AskUserTool:
    """Ask the user a question when clarification is needed."""

    def __init__(self, cli: CLI) -> None:
        self._cli = cli

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return (
            "Ask the user a question when you need clarification before proceeding. "
            "Use this when the request is ambiguous, you need to choose between multiple "
            "approaches, or you need information you can't determine from the codebase."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user.",
                },
            },
            "required": ["question"],
        }

    async def execute(self, *, question: str, **_: Any) -> str:
        self._cli.console.print(f"\n[bold cyan]? {question}[/bold cyan]")
        answer = await self._cli.get_input()
        if answer is None:
            return "(user did not provide an answer)"
        return answer
