"""Memory orchestrator: loads context, flushes data, coordinates search and indexing."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.config import EmbeddingConfig, MemoryConfig
from agent.memory.daily import DailyMemory
from agent.memory.files import MemoryFiles

logger = logging.getLogger(__name__)


class MemoryManager:
    """Orchestrates memory reads, writes, indexing, and search."""

    def __init__(
        self,
        config: MemoryConfig,
        base_dir: Path,
        embedding_config: EmbeddingConfig | None = None,
        history_dir: str = ".agent/history/",
    ) -> None:
        self._config = config
        self._base_dir = base_dir
        self._history_dir = history_dir
        self._files = MemoryFiles(config.memory_file, config.memory_dir, base_dir)
        self._daily = DailyMemory(config.daily_dir, base_dir)
        self._embedding_config = embedding_config
        self._indexer = None
        self._searcher = None

    def _ensure_search(self) -> bool:
        """Lazily initialize embedding indexer and searcher. Returns True if available."""
        if self._searcher is not None:
            return True
        if self._embedding_config is None or not self._embedding_config.enabled:
            return False
        try:
            from agent.embedding.indexer import EmbeddingIndexer
            from agent.embedding.search import HybridSearch

            self._indexer = EmbeddingIndexer(self._embedding_config, self._base_dir)
            self._searcher = HybridSearch(self._embedding_config, self._indexer.store)
            return True
        except Exception as e:
            logger.debug("Embedding search unavailable: %s", e)
            return False

    # ── Context loading (injected into system prompt) ──────────────────

    async def load_context(self) -> str:
        """Load memory content for the system prompt: MEMORY.md + last N days of daily notes."""
        parts = []

        main = self._files.read_main()
        if main:
            parts.append(main)

        # Load last N days of daily notes (configurable, default 2)
        recent_days = self._daily.read_recent(days=self._config.context_days)
        for dt, content in recent_days:
            parts.append(f"\n## Notes — {dt.isoformat()}\n{content}")

        return "\n".join(parts)

    # ── Write operations ───────────────────────────────────────────────

    async def flush(self, data: str, topic: str | None = None) -> None:
        """Write extracted info to memory files and re-index."""
        if topic:
            self._files.append_topic(topic, data)
        else:
            self._files.append_main(data)

        self._daily.append(f"Memory flush: {data[:200]}")

        # Re-index the changed file
        self._index_memory_files()

    async def save(self, content: str, topic: str | None = None) -> str:
        """Save a memory entry (called by the memory_save tool)."""
        if topic:
            self._files.append_topic(topic, content)
            self._index_memory_files()
            return f"Saved to topic '{topic}'."
        else:
            self._files.append_main(content)
            self._index_memory_files()
            return "Saved to main memory."

    async def append_daily(self, entry: str) -> None:
        """Add a timestamped entry to today's daily file."""
        self._daily.append(entry)

    # ── Read operations (for tools) ────────────────────────────────────

    async def read_main(self) -> str:
        return self._files.read_main()

    async def read_topic(self, topic: str) -> str:
        return self._files.read_topic(topic)

    async def list_topics(self) -> list[str]:
        return self._files.list_topics()

    async def read_daily(self, date_str: str | None = None) -> str:
        """Read daily notes. If date_str is None, read today's."""
        if date_str:
            from datetime import date
            dt = date.fromisoformat(date_str)
            return self._daily.read_date(dt)
        return self._daily.read_today()

    async def list_daily_dates(self) -> list[str]:
        return self._daily.list_dates()

    # ── Search ─────────────────────────────────────────────────────────

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Hybrid search across all indexed memory and history."""
        if not self._ensure_search():
            # Fallback: simple text search across memory files
            return self._fallback_search(query, top_k)

        results = self._searcher.search(query, top_k=top_k)
        return [
            {"text": r.chunk_text[:700], "source": r.source, "score": round(r.score, 3)}
            for r in results
        ]

    def _fallback_search(self, query: str, top_k: int) -> list[dict]:
        """Simple keyword search when embeddings are unavailable."""
        query_lower = query.lower()
        results = []

        # Search main memory
        main = self._files.read_main()
        if main and query_lower in main.lower():
            # Extract relevant paragraph
            for para in main.split("\n\n"):
                if query_lower in para.lower():
                    results.append({"text": para[:700], "source": "MEMORY.md", "score": 1.0})

        # Search topic files
        for topic in self._files.list_topics():
            content = self._files.read_topic(topic)
            if content and query_lower in content.lower():
                for para in content.split("\n\n"):
                    if query_lower in para.lower():
                        results.append({"text": para[:700], "source": f"topics/{topic}.md", "score": 0.8})

        # Search recent daily files
        for dt, content in self._daily.read_recent(days=7):
            if query_lower in content.lower():
                for para in content.split("\n\n"):
                    if query_lower in para.lower():
                        results.append({"text": para[:700], "source": f"daily/{dt.isoformat()}.md", "score": 0.6})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # ── Indexing ───────────────────────────────────────────────────────

    def index_all(self) -> int:
        """Index all memory files + conversation history. Called on startup."""
        total = self._index_memory_files()
        total += self._index_history()
        return total

    def _index_memory_files(self) -> int:
        """Index MEMORY.md, topic files, and recent daily notes."""
        if not self._ensure_search():
            return 0

        total = 0
        # Main memory
        main = self._files.read_main()
        if main:
            total += self._indexer.index_text("MEMORY.md", main)

        # Topics
        for topic in self._files.list_topics():
            content = self._files.read_topic(topic)
            if content:
                total += self._indexer.index_text(f"topics/{topic}.md", content)

        # Last 7 days of daily notes
        for dt, content in self._daily.read_recent(days=7):
            total += self._indexer.index_text(f"daily/{dt.isoformat()}.md", content)

        return total

    def _index_history(self) -> int:
        """Index recent conversation history from session JSON files."""
        if not self._ensure_search():
            return 0

        history_dir = self._base_dir / self._history_dir
        if not history_dir.exists():
            return 0

        import json
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=2)
        total = 0

        for path in sorted(history_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            # Only index sessions from last 2 days
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                if mtime < cutoff:
                    continue

                data = json.loads(path.read_text())
                text_parts = []
                for msg in data.get("messages", []):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        text_parts.append(f"[{role}]: {content}")
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(f"[{role}]: {block['text']}")

                if text_parts:
                    session_text = "\n\n".join(text_parts)
                    source = f"history/{path.stem}"
                    total += self._indexer.index_text(source, session_text)
            except Exception:
                continue

        return total

    def index_session(self, session_text: str, session_id: str) -> int:
        """Index a single session after it's saved."""
        if not self._ensure_search():
            return 0
        return self._indexer.index_text(f"history/{session_id}", session_text)

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def files(self) -> MemoryFiles:
        return self._files

    @property
    def daily(self) -> DailyMemory:
        return self._daily
