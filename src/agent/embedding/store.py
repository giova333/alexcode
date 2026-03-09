"""SQLite storage for text chunks and embeddings."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chunk:
    id: int
    source: str
    chunk_text: str
    embedding: list[float]
    updated_at: str


class EmbeddingStore:
    """SQLite-backed storage for text chunks and their embeddings."""

    def __init__(self, db_path: str, base_dir: Path) -> None:
        path = base_dir / db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        self._conn.commit()

    def insert(self, source: str, chunk_text: str, embedding: list[float], updated_at: str) -> int:
        cursor = self._conn.execute(
            "INSERT INTO chunks (source, chunk_text, embedding, updated_at) VALUES (?, ?, ?, ?)",
            (source, chunk_text, json.dumps(embedding), updated_at),
        )
        self._conn.commit()
        return cursor.lastrowid or 0

    def insert_batch(self, items: list[tuple[str, str, list[float], str]]) -> None:
        self._conn.executemany(
            "INSERT INTO chunks (source, chunk_text, embedding, updated_at) VALUES (?, ?, ?, ?)",
            [(s, t, json.dumps(e), u) for s, t, e, u in items],
        )
        self._conn.commit()

    def get_all(self) -> list[Chunk]:
        rows = self._conn.execute(
            "SELECT id, source, chunk_text, embedding, updated_at FROM chunks"
        ).fetchall()
        return [
            Chunk(id=r[0], source=r[1], chunk_text=r[2], embedding=json.loads(r[3]), updated_at=r[4])
            for r in rows
        ]

    def delete_by_source(self, source: str) -> int:
        cursor = self._conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
        self._conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
