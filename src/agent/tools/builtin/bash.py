"""Bash tool: execute shell commands."""

from __future__ import annotations

import asyncio
from typing import Any


class BashTool:
    def __init__(self, timeout: int = 120) -> None:
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout in seconds (default: {self._timeout}).",
                },
            },
            "required": ["command"],
        }

    async def execute(self, *, command: str, timeout: int | None = None, **_: Any) -> str:
        effective_timeout = timeout if timeout is not None else self._timeout
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Command timed out after {effective_timeout}s"

        output_parts = []
        if stdout:
            output_parts.append(stdout.decode(errors="replace"))
        if stderr:
            output_parts.append(f"STDERR:\n{stderr.decode(errors='replace')}")
        if proc.returncode != 0:
            output_parts.append(f"Exit code: {proc.returncode}")

        result = "\n".join(output_parts)
        return result or "(no output)"
