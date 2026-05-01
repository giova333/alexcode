"""MEMORY.md file I/O — long-term, non-temporal knowledge."""

from __future__ import annotations

from pathlib import Path


class MemoryFiles:
    """Reads and writes the main MEMORY.md file (stable, long-term knowledge).

    Absolute paths and ``~``-prefixed paths are used as-is (user-scope file shared
    across projects). Relative paths are resolved under ``base_dir`` (legacy /
    test-time behavior).
    """

    def __init__(self, memory_file: str, base_dir: Path) -> None:
        expanded = Path(memory_file).expanduser()
        self._memory_file = expanded if expanded.is_absolute() else base_dir / expanded

    def read(self) -> str:
        if self._memory_file.exists():
            return self._memory_file.read_text()
        return ""

    def write(self, content: str) -> None:
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        self._memory_file.write_text(content)

    def append(self, content: str) -> None:
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self.read()
        separator = "\n\n" if existing and not existing.endswith("\n\n") else "\n" if existing else ""
        self._memory_file.write_text(existing + separator + content)
