"""Glob tool: find files by pattern."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class GlobTool:
    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files matching a glob pattern. Returns file paths sorted by modification time."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: current directory).",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, *, pattern: str, path: str = ".", **_: Any) -> str:
        base = Path(path).expanduser()
        if not base.is_dir():
            return f"Not a directory: {path}"

        try:
            matches = list(base.glob(pattern))
        except ValueError as e:
            return f"Invalid glob pattern: {e}"

        # Filter to files only, sort by mtime descending
        files = [f for f in matches if f.is_file()]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        if not files:
            return f"No files matching '{pattern}' in {path}"

        # Limit output
        max_results = 100
        lines = [str(f) for f in files[:max_results]]
        if len(files) > max_results:
            lines.append(f"... and {len(files) - max_results} more files")

        return "\n".join(lines)
