"""MEMORY.md and topic file I/O."""

from __future__ import annotations

import re
from pathlib import Path


def _safe_topic_name(topic: str) -> str:
    """Sanitize topic name to prevent path traversal."""
    safe = re.sub(r"[^\w\-]", "_", topic)
    if not safe:
        raise ValueError(f"Invalid topic name: {topic!r}")
    return safe


class MemoryFiles:
    """Reads and writes memory markdown files."""

    def __init__(self, memory_file: str, memory_dir: str, base_dir: Path) -> None:
        self._memory_file = base_dir / memory_file
        self._topics_dir = base_dir / memory_dir / "topics"

    def read_main(self) -> str:
        """Read MEMORY.md content."""
        if self._memory_file.exists():
            return self._memory_file.read_text()
        return ""

    def write_main(self, content: str) -> None:
        """Write MEMORY.md content."""
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        self._memory_file.write_text(content)

    def append_main(self, content: str) -> None:
        """Append to MEMORY.md."""
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self.read_main()
        separator = "\n\n" if existing and not existing.endswith("\n\n") else "\n" if existing else ""
        self._memory_file.write_text(existing + separator + content)

    def read_topic(self, topic: str) -> str:
        """Read a topic file."""
        path = self._topics_dir / f"{_safe_topic_name(topic)}.md"
        if path.exists():
            return path.read_text()
        return ""

    def write_topic(self, topic: str, content: str) -> None:
        """Write a topic file."""
        self._topics_dir.mkdir(parents=True, exist_ok=True)
        path = self._topics_dir / f"{_safe_topic_name(topic)}.md"
        path.write_text(content)

    def append_topic(self, topic: str, content: str) -> None:
        """Append to a topic file."""
        self._topics_dir.mkdir(parents=True, exist_ok=True)
        path = self._topics_dir / f"{_safe_topic_name(topic)}.md"
        existing = path.read_text() if path.exists() else ""
        separator = "\n\n" if existing and not existing.endswith("\n\n") else "\n" if existing else ""
        path.write_text(existing + separator + content)

    def list_topics(self) -> list[str]:
        """List available topic file names (without .md)."""
        if not self._topics_dir.exists():
            return []
        return [p.stem for p in self._topics_dir.glob("*.md")]
