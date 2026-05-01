"""Memory orchestrator: MEMORY.md I/O + delegates search/ingest to mem0."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.config import MemoryConfig
from agent.core.message import Message
from agent.memory.files import MemoryFiles
from agent.memory.mem0_client import Mem0Client

logger = logging.getLogger(__name__)


class MemoryManager:
    """Orchestrates memory reads, writes, and search.

    Two storage layers:
      - MEMORY.md: stable, long-term knowledge (project conventions, user prefs, architecture)
      - mem0: continuously-ingested memories distilled from conversation messages.
              Scope ('project' vs 'global') is set via MemoryConfig.scope.
    """

    def __init__(
        self,
        config: MemoryConfig,
        base_dir: Path,
        mem0_client: Mem0Client | None = None,
    ) -> None:
        self._config = config
        self._base_dir = base_dir
        self._files = MemoryFiles(config.memory_file, base_dir)
        self._mem0 = mem0_client

    # ── Context loading (injected into system prompt) ──────────────────

    async def load_context(self) -> str:
        """Load MEMORY.md content for the system prompt."""
        return self._files.read()

    # ── Write operations ───────────────────────────────────────────────

    async def save_main(self, content: str) -> str:
        """Save to MEMORY.md (stable, long-term knowledge only)."""
        self._files.append(content)
        return "Saved to MEMORY.md."

    # ── Read operations (for tools) ────────────────────────────────────

    async def read_main(self) -> str:
        return self._files.read()

    # ── Search ─────────────────────────────────────────────────────────

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Search mem0 indexes (project + optional global)."""
        if self._mem0 is None:
            return []
        return await self._mem0.search(query, top_k=top_k)

    # ── Live message hook (wired into Conversation.on_append) ──────────

    def handle_message_appended(self, message: Message) -> None:
        """Forward user/assistant text messages to mem0 ingestion queue."""
        if self._mem0 is None:
            return
        self._mem0.enqueue_message(message)

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def files(self) -> MemoryFiles:
        return self._files

    @property
    def mem0(self) -> Mem0Client | None:
        return self._mem0
