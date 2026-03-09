"""Read tool: read file contents with line numbers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ReadTool:
    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return "Read a file and return its contents with line numbers."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read.",
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, *, file_path: str, offset: int = 1, limit: int = 2000, **_: Any) -> str:
        path = Path(file_path).expanduser()
        if not path.exists():
            return f"File not found: {file_path}"
        if not path.is_file():
            return f"Not a file: {file_path}"

        try:
            text = path.read_text(errors="replace")
        except PermissionError:
            return f"Permission denied: {file_path}"

        lines = text.splitlines()
        start = max(0, offset - 1)
        end = start + limit
        selected = lines[start:end]

        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            # Truncate long lines
            if len(line) > 2000:
                line = line[:2000] + "..."
            numbered.append(f"{i:>6}\t{line}")

        return "\n".join(numbered) or "(empty file)"
