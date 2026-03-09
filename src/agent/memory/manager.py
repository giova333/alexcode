"""Memory orchestrator: loads context, flushes data, coordinates search."""

from __future__ import annotations

from pathlib import Path

from agent.config import MemoryConfig
from agent.memory.daily import DailyMemory
from agent.memory.files import MemoryFiles


class MemoryManager:
    """Orchestrates memory reads and writes."""

    def __init__(self, config: MemoryConfig, base_dir: Path) -> None:
        self._config = config
        self._files = MemoryFiles(config.memory_file, config.memory_dir, base_dir)
        self._daily = DailyMemory(config.daily_dir, base_dir)

    async def load_context(self) -> str:
        """Load memory content to inject into system prompt."""
        parts = []

        main = self._files.read_main()
        if main:
            parts.append(main)

        today = self._daily.read_today()
        if today:
            parts.append(f"\n## Today's Notes\n{today}")

        return "\n".join(parts)

    async def flush(self, data: str, topic: str | None = None) -> None:
        """Write extracted info to memory files."""
        if topic:
            self._files.append_topic(topic, data)
        else:
            self._files.append_main(data)

        # Also add a daily entry
        self._daily.append(f"Memory flush: {data[:200]}")

    async def append_daily(self, entry: str) -> None:
        """Add a timestamped entry to today's daily file."""
        self._daily.append(entry)

    @property
    def files(self) -> MemoryFiles:
        return self._files

    @property
    def daily(self) -> DailyMemory:
        return self._daily
