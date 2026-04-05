"""Index text chunks into embeddings + BM25, with content-hash dedup."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.config import EmbeddingConfig
from agent.embedding.model import get_embedding_model
from agent.embedding.store import EmbeddingStore


class EmbeddingIndexer:
    """Chunks text, generates embeddings, and stores them. Skips unchanged content."""

    def __init__(self, config: EmbeddingConfig, base_dir: Path) -> None:
        self._config = config
        self._store = EmbeddingStore(config.db_path, base_dir)

    def _get_model(self) -> Any:
        """Return shared embedding model (lazy-loaded on first call)."""
        return get_embedding_model(self._config.model)

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def index_text(self, source: str, text: str, force: bool = False) -> int:
        """Chunk text and index embeddings. Skips if content unchanged.

        Returns number of chunks created (0 if skipped).
        """
        content_hash = self._content_hash(text)

        # Skip if content hasn't changed
        if not force:
            stored_hash = self._store.get_source_hash(source)
            if stored_hash == content_hash:
                return 0

        # Content changed — re-index
        self._store.delete_by_source(source)

        chunks = self._chunk_text(text)
        if not chunks:
            return 0

        model = self._get_model()
        embeddings = model.encode(chunks, show_progress_bar=False).tolist()
        now = datetime.now().isoformat()

        items = [(source, chunk, emb, now) for chunk, emb in zip(chunks, embeddings)]
        self._store.insert_batch(items)
        self._store.set_source_hash(source, content_hash, now)
        return len(chunks)

    def index_file(self, file_path: Path) -> int:
        """Index a single file."""
        if not file_path.exists():
            return 0
        text = file_path.read_text(errors="replace")
        return self.index_text(str(file_path), text)

    def index_directory(self, dir_path: Path, glob_pattern: str = "**/*.md") -> int:
        """Index all matching files in a directory."""
        total = 0
        for path in dir_path.glob(glob_pattern):
            if path.is_file():
                total += self.index_file(path)
        return total

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks."""
        words = text.split()
        if not words:
            return []

        chunk_size = self._config.chunk_size
        overlap = self._config.chunk_overlap
        step = max(1, chunk_size - overlap)

        chunks = []
        for i in range(0, len(words), step):
            chunk = " ".join(words[i:i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
            if i + chunk_size >= len(words):
                break

        return chunks

    @property
    def store(self) -> EmbeddingStore:
        return self._store

