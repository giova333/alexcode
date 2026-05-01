"""mem0-backed memory: single project- or globally-scoped index, async ingestion."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent.config import Mem0Config
from agent.core.message import Message

logger = logging.getLogger(__name__)


class Mem0Client:
    """Owns a single mem0.Memory instance and a background ingestion worker.

    The ``scope`` argument selects where memories live:
      - ``"project"``: store at config.project_store_dir, user_id = absolute project path
      - ``"global"``:  store at config.global_store_dir,  user_id = "global"
    """

    _SENTINEL: dict[str, Any] = {"__stop__": True}

    def __init__(
        self,
        config: Mem0Config,
        scope: str,
        project_dir: Path,
    ) -> None:
        if scope not in ("project", "global"):
            raise ValueError(f"Invalid mem0 scope: {scope!r}; expected 'project' or 'global'")
        self._config = config
        self._scope = scope
        if scope == "project":
            self._user_id = str(project_dir.resolve())
            self._store_dir = config.project_store_dir
            self._collection = "project_memories"
        else:
            self._user_id = "global"
            self._store_dir = config.global_store_dir
            self._collection = "global_memories"
        self._memory: Any | None = None
        self._init_lock = asyncio.Lock()
        self._init_attempted = False
        self._queue: asyncio.Queue | None = None
        self._worker_task: asyncio.Task | None = None

    @property
    def scope(self) -> str:
        return self._scope

    # ── Lazy initialization ────────────────────────────────────────────

    async def _ensure_init(self) -> bool:
        """Build the mem0 Memory instance on first use, off the event loop."""
        if self._init_attempted:
            return self._memory is not None
        async with self._init_lock:
            if self._init_attempted:
                return self._memory is not None
            try:
                self._memory = await asyncio.to_thread(self._build_memory)
                store = str(Path(self._store_dir).expanduser().resolve())
                logger.info(
                    "mem0 ready: scope=%s, user_id=%s, store=%s",
                    self._scope, self._user_id, store,
                )
            except Exception as e:
                logger.warning(
                    "mem0 init failed (scope=%s): %s — search and ingest disabled. "
                    "Check api keys (ANTHROPIC_API_KEY for llm, OPENAI_API_KEY for embedder) "
                    "and that 'chromadb' is installed.",
                    self._scope, e,
                )
                self._memory = None
            self._init_attempted = True
            return self._memory is not None

    def _build_memory(self) -> Any:
        from mem0 import Memory

        abs_path = str(Path(self._store_dir).expanduser().resolve())
        Path(abs_path).mkdir(parents=True, exist_ok=True)
        config_dict = {
            "llm": {
                "provider": self._config.llm.provider,
                "config": {
                    "model": self._config.llm.model,
                    "api_key": self._config.llm.api_key,
                },
            },
            "embedder": {
                "provider": self._config.embedder.provider,
                "config": {
                    "model": self._config.embedder.model,
                    "api_key": self._config.embedder.api_key,
                },
            },
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": self._collection,
                    "path": abs_path,
                },
            },
        }
        return Memory.from_config(config_dict)

    # ── Live ingestion ─────────────────────────────────────────────────

    def enqueue_message(self, message: Message) -> None:
        """Queue a message for ingestion. Filters non-text and non-user/assistant messages."""
        if message.role not in ("user", "assistant"):
            return
        text = message.text.strip()
        if not text:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Mem0Client.enqueue_message called outside event loop; dropping")
            return
        if self._queue is None:
            self._queue = asyncio.Queue()
            self._worker_task = loop.create_task(self._worker())
        self._queue.put_nowait({"role": message.role, "content": text})

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            if item is self._SENTINEL:
                return
            try:
                await self._dispatch_add(item)
            except Exception as e:
                logger.warning("mem0 ingest failed (scope=%s): %s", self._scope, e)

    async def _dispatch_add(self, payload: dict[str, Any]) -> None:
        if not await self._ensure_init():
            return
        preview = payload.get("content", "")[:80].replace("\n", " ")
        logger.debug("mem0 ingest [%s]: %s", payload.get("role", "?"), preview)
        await asyncio.to_thread(self._memory.add, [payload], user_id=self._user_id)

    def _search_kwargs(self, top_k: int) -> dict[str, Any]:
        """mem0 v2 takes filters={'user_id': ...}; older versions take user_id=... directly."""
        return {"filters": {"user_id": self._user_id}, "limit": top_k}

    # ── Search ─────────────────────────────────────────────────────────

    async def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Search the configured scope. Each result tagged with source=scope."""
        if not await self._ensure_init():
            logger.warning("mem0 search skipped: index not initialized (scope=%s)", self._scope)
            return []

        try:
            hits = await asyncio.to_thread(
                self._memory.search, query, **self._search_kwargs(top_k)
            )
        except TypeError:
            # Pre-v2 mem0 used user_id= directly.
            try:
                hits = await asyncio.to_thread(
                    self._memory.search, query, user_id=self._user_id, limit=top_k
                )
            except Exception as e:
                logger.warning("mem0 search failed (scope=%s): %s", self._scope, e)
                return []
        except Exception as e:
            logger.warning("mem0 search failed (scope=%s): %s", self._scope, e)
            return []

        results = self._normalize_hits(hits, self._scope)
        results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        logger.info(
            "mem0 search (scope=%s) query=%r → %d hit(s)",
            self._scope, query[:60], len(results),
        )
        return results[:top_k]

    @staticmethod
    def _normalize_hits(hits: Any, source: str) -> list[dict[str, Any]]:
        """Coerce mem0's varied return shapes into a flat list of result dicts."""
        if isinstance(hits, dict) and "results" in hits:
            raw = hits["results"]
        elif isinstance(hits, list):
            raw = hits
        else:
            return []

        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = item.get("memory") or item.get("text") or ""
            score = item.get("score", 0.0)
            try:
                score_val = round(float(score), 3)
            except (TypeError, ValueError):
                score_val = 0.0
            out.append({"text": text, "source": source, "score": score_val})
        return out

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Drain any pending ingestion and stop the worker."""
        if self._queue is None or self._worker_task is None:
            return
        try:
            self._queue.put_nowait(self._SENTINEL)
            await asyncio.wait_for(self._worker_task, timeout=10.0)
        except asyncio.TimeoutError:
            self._worker_task.cancel()
        except Exception as e:
            logger.debug("mem0 worker shutdown error: %s", e)
