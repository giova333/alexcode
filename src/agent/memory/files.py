"""MEMORY.md file I/O — long-term, non-temporal knowledge."""

from __future__ import annotations

from pathlib import Path


class MemoryFiles:
    """Reads and writes the main MEMORY.md file (stable, long-term knowledge)."""

    def __init__(self, memory_file: str, base_dir: Path) -> None:
        self._memory_file = base_dir / memory_file

    def read(self) -> str:
        """Read MEMORY.md content."""
        if self._memory_file.exists():
            return self._memory_file.read_text()
        return ""

    def write(self, content: str) -> None:
        """Overwrite MEMORY.md content."""
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        self._memory_file.write_text(content)

    def append(self, content: str) -> None:
        """Append to MEMORY.md."""
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self.read()
        separator = "\n\n" if existing and not existing.endswith("\n\n") else "\n" if existing else ""
        self._memory_file.write_text(existing + separator + content)
