"""Memory orchestrator: loads context, flushes data, coordinates search and indexing."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.config import EmbeddingConfig, MemoryConfig
from agent.memory.daily import DailyMemory
from agent.memory.files import MemoryFiles

logger = logging.getLogger(__name__)


class MemoryManager:
    """Orchestrates memory reads, writes, indexing, and search.

    Two storage layers:
      - MEMORY.md: stable, long-term knowledge (project conventions, user prefs, architecture)
      - daily/YYYY-MM-DD.md: everything else (session notes, decisions, discoveries, activity)
    """

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
        self._files = MemoryFiles(config.memory_file, base_dir)
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

        main = self._files.read()
        if main:
            parts.append(main)

        recent_days = self._daily.read_recent(days=self._config.context_days)
        for dt, content in recent_days:
            parts.append(f"\n## Notes — {dt.isoformat()}\n{content}")

        return "\n".join(parts)

    # ── Write operations ───────────────────────────────────────────────

    async def save_daily(self, content: str) -> str:
        """Save to today's daily file (default destination for most memory writes)."""
        self._daily.append(content)
        self._index_memory_files()
        return "Saved to today's daily notes."

    async def save_main(self, content: str) -> str:
        """Save to MEMORY.md (stable, long-term knowledge only)."""
        self._files.append(content)
        self._index_memory_files()
        return "Saved to MEMORY.md."

    async def append_daily(self, entry: str) -> None:
        """Add a timestamped entry to today's daily file."""
        self._daily.append(entry)

    # ── Read operations (for tools) ────────────────────────────────────

    async def read_main(self) -> str:
        return self._files.read()

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

        main = self._files.read()
        if main and query_lower in main.lower():
            for para in main.split("\n\n"):
                if query_lower in para.lower():
                    results.append({"text": para[:700], "source": "MEMORY.md", "score": 1.0})

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
        """Index MEMORY.md and recent daily notes."""
        if not self._ensure_search():
            return 0

        total = 0
        main = self._files.read()
        if main:
            total += self._indexer.index_text("MEMORY.md", main)

        for dt, content in self._daily.read_recent(days=7):
            total += self._indexer.index_text(f"daily/{dt.isoformat()}.md", content)

        return total

    def _index_history(self) -> int:
        """Index recent conversation history from session JSONL (and legacy JSON) files."""
        if not self._ensure_search():
            return 0

        history_dir = self._base_dir / self._history_dir
        if not history_dir.exists():
            return 0

        import json
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=2)
        total = 0

        # Index JSONL files (current format)
        for path in sorted(history_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                if mtime < cutoff:
                    continue
                text_parts = []
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("type") != "message":
                            continue
                        role = obj.get("role", "")
                        content = obj.get("content", "")
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

        # Legacy: index any remaining .json files
        for path in sorted(history_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
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
