"""Grep tool: search file contents using ripgrep or grep."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any


class GrepTool:
    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search file contents for a regex pattern. Uses ripgrep if available, falls back to grep."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search (default: current directory).",
                },
                "glob": {
                    "type": "string",
                    "description": "File glob filter (e.g. '*.py').",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case insensitive search (default: false).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default: 50).",
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        *,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        case_insensitive: bool = False,
        max_results: int = 50,
        **_: Any,
    ) -> str:
        use_rg = shutil.which("rg") is not None

        if use_rg:
            cmd = ["rg", "--no-heading", "--line-number", f"--max-count={max_results}"]
            if case_insensitive:
                cmd.append("-i")
            if glob:
                cmd.extend(["--glob", glob])
            cmd.extend([pattern, path])
        else:
            cmd = ["grep", "-rn"]
            if case_insensitive:
                cmd.append("-i")
            cmd.extend([pattern, path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            return "Search timed out after 30s"

        output = stdout.decode(errors="replace")
        if not output:
            if proc.returncode == 1:
                return f"No matches found for '{pattern}'"
            if stderr:
                return f"Error: {stderr.decode(errors='replace')}"
            return f"No matches found for '{pattern}'"

        lines = output.splitlines()
        if len(lines) > max_results:
            lines = lines[:max_results]
            lines.append(f"... (truncated to {max_results} results)")

        return "\n".join(lines)
