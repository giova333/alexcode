"""Edit tool: targeted string replacement in files."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class EditTool:
    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing an exact string match. "
            "The old_string must appear exactly once in the file (unless replace_all is true)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit.",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace.",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false).",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    async def execute(
        self,
        *,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        **_: Any,
    ) -> str:
        path = Path(file_path).expanduser()
        if not path.exists():
            return f"File not found: {file_path}"

        try:
            content = path.read_text()
        except PermissionError:
            return f"Permission denied: {file_path}"

        count = content.count(old_string)
        if count == 0:
            return f"old_string not found in {file_path}"
        if count > 1 and not replace_all:
            return (
                f"old_string found {count} times in {file_path}. "
                "Provide more context to make it unique, or set replace_all=true."
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        path.write_text(new_content)
        replacements = count if replace_all else 1
        return f"Replaced {replacements} occurrence(s) in {file_path}"
