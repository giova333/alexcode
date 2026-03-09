"""Write tool: create or overwrite files."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class WriteTool:
    @property
    def name(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return "Write content to a file, creating parent directories as needed."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write.",
                },
            },
            "required": ["file_path", "content"],
        }

    async def execute(self, *, file_path: str, content: str, **_: Any) -> str:
        path = Path(file_path).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return f"Wrote {len(content)} bytes to {file_path}"
        except PermissionError:
            return f"Permission denied: {file_path}"
        except OSError as e:
            return f"Error writing {file_path}: {e}"
