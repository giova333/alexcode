"""Skill data model following Anthropic's Agent Skills convention.

Skills are directories containing a SKILL.md file with YAML frontmatter:

    .agent/skills/my-skill/SKILL.md
    ---
    name: my-skill
    description: Does something useful. Use when the user asks about X.
    user-invocable: true
    disable-model-invocation: false
    argument-hint: "[filename]"
    allowed-tools: Read, Grep, Glob
    ---

    Full instructions loaded when skill is invoked...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    """A skill following the Agent Skills specification."""
    name: str
    description: str = ""
    user_invocable: bool = True
    disable_model_invocation: bool = False
    argument_hint: str = ""
    allowed_tools: list[str] = field(default_factory=list)

    # Internal fields
    skill_dir: Path | None = None   # directory containing SKILL.md
    _body: str | None = None        # lazily loaded SKILL.md body (below frontmatter)

    def load_body(self) -> str:
        """Load the full SKILL.md body (instructions below frontmatter).

        Uses progressive loading: body is only read from disk on invocation.
        """
        if self._body is not None:
            return self._body

        if self.skill_dir is None:
            return ""

        skill_file = self.skill_dir / "SKILL.md"
        if not skill_file.exists():
            return ""

        content = skill_file.read_text()
        self._body = _extract_body(content)
        return self._body

    def render(self, arguments: str = "") -> str:
        """Render the skill body with argument substitution.

        Supports:
          $ARGUMENTS      - all arguments
          $ARGUMENTS[N]   - specific argument by index
          $0, $1, $2      - shorthand for $ARGUMENTS[N]
          !`command`       - dynamic context (shell command output)
        """
        body = self.load_body()
        if not body:
            return ""

        # Argument substitution
        if arguments:
            args_list = arguments.split()
            body = body.replace("$ARGUMENTS", arguments)
            for i, arg in enumerate(args_list):
                body = body.replace(f"$ARGUMENTS[{i}]", arg)
                body = body.replace(f"${i}", arg)
        elif "$ARGUMENTS" not in body and arguments:
            body += f"\nARGUMENTS: {arguments}"

        # Dynamic context: !`command` preprocessing
        body = _resolve_dynamic_context(body)

        return body


def _extract_body(content: str) -> str:
    """Extract the markdown body below YAML frontmatter."""
    if not content.startswith("---"):
        return content

    # Find closing ---
    end = content.find("---", 3)
    if end == -1:
        return content

    # Skip past the closing --- and any immediate newline
    body_start = end + 3
    if body_start < len(content) and content[body_start] == "\n":
        body_start += 1

    return content[body_start:].strip()


def _resolve_dynamic_context(body: str) -> str:
    """Replace !`command` patterns with shell command output."""
    import re
    import subprocess

    def run_command(match: re.Match) -> str:
        cmd = match.group(1)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else f"(command failed: {cmd})"
        except subprocess.TimeoutExpired:
            return f"(command timed out: {cmd})"
        except Exception:
            return f"(command error: {cmd})"

    return re.sub(r"!`([^`]+)`", run_command, body)
