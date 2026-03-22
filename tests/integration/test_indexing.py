"""Integration tests for the embedding indexer and store (no ML model needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import EmbeddingConfig
from agent.embedding.store import EmbeddingStore


# ---------------------------------------------------------------------------
# EmbeddingStore (SQLite)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestEmbeddingStore:

    @pytest.fixture
    def store(self, tmp_path: Path) -> EmbeddingStore:
        s = EmbeddingStore(".agent/embeddings.db", tmp_path)
        yield s
        s.close()

    def test_insert_and_count(self, store: EmbeddingStore):
        store.insert("test_source", "hello world", [0.1, 0.2, 0.3], "2025-01-01")
        assert store.count() == 1

    def test_insert_batch(self, store: EmbeddingStore):
        items = [
            ("src1", "chunk 1", [0.1, 0.2], "2025-01-01"),
            ("src1", "chunk 2", [0.3, 0.4], "2025-01-01"),
            ("src2", "chunk 3", [0.5, 0.6], "2025-01-01"),
        ]
        store.insert_batch(items)
        assert store.count() == 3

    def test_get_all(self, store: EmbeddingStore):
        store.insert("src", "text", [1.0, 2.0], "2025-01-01")
        chunks = store.get_all()
        assert len(chunks) == 1
        assert chunks[0].chunk_text == "text"
        assert chunks[0].source == "src"
        assert chunks[0].embedding == [1.0, 2.0]

    def test_delete_by_source(self, store: EmbeddingStore):
        store.insert("keep", "a", [0.1], "2025-01-01")
        store.insert("delete_me", "b", [0.2], "2025-01-01")
        assert store.count() == 2

        deleted = store.delete_by_source("delete_me")
        assert deleted == 1
        assert store.count() == 1

    def test_source_hash_tracking(self, store: EmbeddingStore):
        assert store.get_source_hash("file.md") is None

        store.set_source_hash("file.md", "abc123", "2025-01-01")
        assert store.get_source_hash("file.md") == "abc123"

        # Update
        store.set_source_hash("file.md", "def456", "2025-01-02")
        assert store.get_source_hash("file.md") == "def456"

    def test_delete_clears_hash(self, store: EmbeddingStore):
        store.insert("src", "text", [0.1], "2025-01-01")
        store.set_source_hash("src", "hash1", "2025-01-01")
        store.delete_by_source("src")
        assert store.get_source_hash("src") is None


# ---------------------------------------------------------------------------
# EmbeddingIndexer (chunking + dedup, no model required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestEmbeddingIndexerChunking:
    """Test the chunking logic without loading the ML model."""

    @pytest.fixture
    def indexer_config(self) -> EmbeddingConfig:
        return EmbeddingConfig(
            enabled=True,
            model="all-MiniLM-L6-v2",
            db_path=".agent/test_embeddings.db",
            chunk_size=10,  # 10 words per chunk
            chunk_overlap=2,
        )

    def test_chunk_text(self, indexer_config: EmbeddingConfig, tmp_path: Path):
        from agent.embedding.indexer import EmbeddingIndexer

        indexer = EmbeddingIndexer(indexer_config, tmp_path)
        text = " ".join(f"word{i}" for i in range(25))
        chunks = indexer._chunk_text(text)

        # With 10-word chunks and 2-word overlap (step=8), expect ~3-4 chunks
        assert len(chunks) >= 3
        # Each chunk should have at most 10 words
        for chunk in chunks:
            assert len(chunk.split()) <= 10

    def test_chunk_empty_text(self, indexer_config: EmbeddingConfig, tmp_path: Path):
        from agent.embedding.indexer import EmbeddingIndexer

        indexer = EmbeddingIndexer(indexer_config, tmp_path)
        assert indexer._chunk_text("") == []
        assert indexer._chunk_text("   ") == []

    def test_content_hash_deterministic(self, tmp_path: Path):
        from agent.embedding.indexer import EmbeddingIndexer

        h1 = EmbeddingIndexer._content_hash("hello world")
        h2 = EmbeddingIndexer._content_hash("hello world")
        h3 = EmbeddingIndexer._content_hash("different text")
        assert h1 == h2
        assert h1 != h3
