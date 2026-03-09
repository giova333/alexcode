"""Hybrid search: semantic (cosine) + BM25 keyword search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from agent.config import EmbeddingConfig
from agent.embedding.store import Chunk, EmbeddingStore


@dataclass
class SearchResult:
    chunk_text: str
    source: str
    score: float


class HybridSearch:
    """Combines semantic similarity and BM25 for search."""

    def __init__(self, config: EmbeddingConfig, store: EmbeddingStore) -> None:
        self._config = config
        self._store = store
        self._model: Any = None
        self._bm25: Any = None
        self._chunks: list[Chunk] = []

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._config.model)
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. Install with: pip install ai-agent[embedding]"
                )
        return self._model

    def _rebuild_bm25(self) -> None:
        """Rebuild BM25 index from stored chunks."""
        self._chunks = self._store.get_all()
        if not self._chunks:
            self._bm25 = None
            return

        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            self._bm25 = None
            return

        tokenized = [chunk.chunk_text.lower().split() for chunk in self._chunks]
        self._bm25 = BM25Okapi(tokenized)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Hybrid search combining semantic and BM25 scores."""
        self._rebuild_bm25()

        if not self._chunks:
            return []

        alpha = self._config.hybrid_alpha

        # Semantic search
        semantic_scores = self._semantic_search(query)

        # BM25 search
        bm25_scores = self._bm25_search(query)

        # Combine scores
        results: list[tuple[int, float]] = []
        for i in range(len(self._chunks)):
            sem = semantic_scores[i] if i < len(semantic_scores) else 0.0
            bm = bm25_scores[i] if i < len(bm25_scores) else 0.0
            combined = alpha * sem + (1 - alpha) * bm
            results.append((i, combined))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        return [
            SearchResult(
                chunk_text=self._chunks[idx].chunk_text,
                source=self._chunks[idx].source,
                score=score,
            )
            for idx, score in results[:top_k]
            if score > 0
        ]

    def _semantic_search(self, query: str) -> list[float]:
        """Compute cosine similarity between query and all chunks."""
        model = self._get_model()
        query_emb = model.encode([query], show_progress_bar=False)[0]

        scores = []
        for chunk in self._chunks:
            chunk_emb = np.array(chunk.embedding)
            similarity = np.dot(query_emb, chunk_emb) / (
                np.linalg.norm(query_emb) * np.linalg.norm(chunk_emb) + 1e-8
            )
            # Normalize to [0, 1]
            scores.append(float(max(0, (similarity + 1) / 2)))
        return scores

    def _bm25_search(self, query: str) -> list[float]:
        """Get BM25 scores for query against all chunks."""
        if self._bm25 is None:
            return [0.0] * len(self._chunks)

        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens).tolist()

        # Normalize to [0, 1]
        max_score = max(scores) if scores else 1.0
        if max_score > 0:
            scores = [s / max_score for s in scores]
        return scores
