"""Terminal UI: input via prompt_toolkit, output via rich."""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from agent.completer import AgentCompleter


class CLI:
    """Handles all terminal input/output."""

    def __init__(self, working_dir: Path | None = None) -> None:
        self.console = Console()
        history_path = Path.home() / ".config" / "agent" / "input_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self._completer = AgentCompleter(working_dir=working_dir)
        self._session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            completer=self._completer,
            complete_while_typing=True,
        )

    def set_skills(self, skills: list[tuple[str, str]]) -> None:
        """Update available skill commands for autocompletion."""
        self._completer.set_skills(skills)

    def print_welcome(self, provider: str, model: str) -> None:
        kitten = (
            "[bold cyan]"
            "    /\\_/\\  \n"
            "   ( o.o ) \n"
            "    > ^ <  \n"
            "   /|   |\\ \n"
            "  (_|   |_)\n"
            "[/bold cyan]"
        )
        info = (
            f"[bold white]alexcode[/bold white] [dim]— {provider}/{model}[/dim]\n"
            "\n"
            "[dim]Type your message and press Enter. Use \\\\ for multiline.\n"
            "Commands: /exit, /clear, /history, /model\n"
            "Use @ for file references, / for commands. Tab to select.[/dim]"
        )
        self.console.print()
        self.console.print(
            Panel(
                f"{kitten}\n{info}",
                border_style="bright_blue",
                padding=(1, 3),
            )
        )

    async def get_input(self) -> str | None:
        """Get user input. Returns None on EOF/Ctrl+D."""
        try:
            lines: list[str] = []
            while True:
                prompt = ">>> " if not lines else "... "
                line = await self._session.prompt_async(prompt)
                if line.endswith("\\"):
                    lines.append(line[:-1])
                    continue
                lines.append(line)
                break
            return "\n".join(lines).strip() or None
        except (EOFError, KeyboardInterrupt):
            return None

    def print_assistant_text(self, text: str) -> None:
        """Render assistant text as markdown."""
        self.console.print()
        self.console.print(Markdown(text))
        self.console.print()

    def print_text_delta(self, text: str) -> None:
        """Print a streaming text chunk (no newline)."""
        self.console.print(text, end="", highlight=False)

    def print_thinking_delta(self, text: str) -> None:
        """Print a streaming thinking chunk (dimmed)."""
        self.console.print(Text(text, style="dim italic"), end="", highlight=False)

    def start_thinking(self) -> None:
        """Called when thinking block starts."""
        self.console.print(Text("  Thinking...", style="dim italic"))

    def end_thinking(self) -> None:
        """Called when thinking block ends."""
        self.console.print()

    def start_response(self) -> None:
        """Called before streaming starts."""
        self.console.print()

    def end_response(self) -> None:
        """Called after streaming ends."""
        self.console.print()
        self.console.print()

    def print_tool_use(self, name: str, input_data: dict) -> None:
        """Show that a tool is being called."""
        self.console.print(
            Text(f"  ⚡ {name}", style="bold yellow"),
            highlight=False,
        )

    def print_tool_result(self, name: str, result: str, is_error: bool = False) -> None:
        """Show tool result summary."""
        style = "red" if is_error else "dim"
        preview = result[:200] + "..." if len(result) > 200 else result
        self.console.print(Text(f"  ← {preview}", style=style))

    def print_error(self, message: str) -> None:
        self.console.print(f"[bold red]Error:[/bold red] {message}")

    def print_info(self, message: str) -> None:
        self.console.print(f"[dim]{message}[/dim]")

    def print_compaction_notice(self) -> None:
        self.console.print("[dim]📦 Compacting conversation...[/dim]")

    def print_usage(self, input_tokens: int, output_tokens: int) -> None:
        total = input_tokens + output_tokens
        self.console.print(
            f"[dim]tokens: {input_tokens:,} in / {output_tokens:,} out / {total:,} total[/dim]"
        )
