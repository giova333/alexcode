"""Custom prompt_toolkit completer for @ file references and / commands."""

from __future__ import annotations

import os
from pathlib import Path
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


# Built-in slash commands with short descriptions
BUILTIN_COMMANDS: dict[str, str] = {
    "/exit": "Exit the agent",
    "/quit": "Exit the agent",
    "/clear": "Clear conversation",
    "/history": "Show message history",
    "/tokens": "Show token count",
    "/tools": "List available tools",
    "/sessions": "List saved sessions",
    "/resume": "Resume a previous session",
    "/compact": "Compact conversation",
    "/skills": "List available skills",
    "/model": "Switch LLM model",
    "/effort": "Set reasoning effort (low|medium|high|xhigh|max|auto)",
    "/prompt": "Show system prompt",
    "/help": "Show available commands",
    "/plan": "Toggle plan mode",
}


class AgentCompleter(Completer):
    """Completer that handles @ file/folder references and / commands."""

    def __init__(self, working_dir: Path | None = None) -> None:
        self._working_dir = working_dir or Path.cwd()
        self._skill_commands: dict[str, str] = {}

    def set_skills(self, skills: list[tuple[str, str]]) -> None:
        """Update available skill commands. Each tuple is (name, description)."""
        self._skill_commands = {f"/{name}": desc for name, desc in skills}

    def get_completions(self, document: Document, complete_event: object) -> ...:
        text = document.text_before_cursor

        # / command completion — only at the start of the line
        if text.startswith("/"):
            yield from self._complete_commands(text)
            return

        # @ file/folder completion — find the last @ token
        at_idx = text.rfind("@")
        if at_idx != -1:
            # Make sure @ is at start or preceded by whitespace
            if at_idx == 0 or text[at_idx - 1] in (" ", "\t"):
                partial = text[at_idx + 1:]
                yield from self._complete_paths(partial)
                return

    def _complete_commands(self, text: str) -> ...:
        """Complete slash commands."""
        all_commands = {**BUILTIN_COMMANDS, **self._skill_commands}
        for cmd, desc in sorted(all_commands.items()):
            if cmd.startswith(text.lower()):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=desc,
                )

    def _complete_paths(self, partial: str) -> ...:
        """Complete file/folder paths after @."""
        try:
            if os.sep in partial or "/" in partial:
                # Has directory component
                dirname = os.path.dirname(partial)
                basename = os.path.basename(partial)
                search_dir = self._working_dir / dirname
            else:
                dirname = ""
                basename = partial
                search_dir = self._working_dir

            if not search_dir.is_dir():
                return

            entries = []
            try:
                entries = list(search_dir.iterdir())
            except PermissionError:
                return

            # Show hidden entries only when user explicitly types "."
            show_hidden = basename.startswith(".")
            if not show_hidden:
                entries = [e for e in entries if not e.name.startswith(".")]
            entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

            for entry in entries:
                name = entry.name
                if not name.lower().startswith(basename.lower()):
                    continue

                rel_path = os.path.join(dirname, name) if dirname else name
                if entry.is_dir():
                    rel_path += "/"

                display = name + ("/" if entry.is_dir() else "")
                meta = "folder" if entry.is_dir() else "file"

                yield Completion(
                    rel_path,
                    start_position=-len(partial),
                    display=display,
                    display_meta=meta,
                )
        except Exception:
            return
