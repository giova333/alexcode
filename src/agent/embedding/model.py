"""Shared embedding model cache — loads the model once per process."""

from __future__ import annotations

from typing import Any

_cache: dict[str, Any] = {}


def get_embedding_model(model_name: str) -> Any:
    """Return a cached SentenceTransformer, loading it on first call."""
    if model_name not in _cache:
        try:
            from sentence_transformers import SentenceTransformer
            _cache[model_name] = SentenceTransformer(model_name)
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. Install with: pip install ai-agent[embedding]"
            )
    return _cache[model_name]
