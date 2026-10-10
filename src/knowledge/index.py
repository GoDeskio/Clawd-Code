"""Per-user SQLite index for knowledge documents and passages."""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class DocumentRecord:
    doc_id: str
    filename: str
    source_path: str
    added_at: str
    method: str
    passages: int


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    filename: str
    ordinal: int
    text: str
    embedding: tuple[float, ...] | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    added_at TEXT NOT NULL,
    method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(source_path);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pack(vector: list[float] | None) -> bytes | None:
    if not vector:
        return None
    return struct.pack(f"<{len(vector)}f", *[float(value) for value in vector])


def _unpack(blob: bytes | memoryview | None) -> tuple[float, ...] | None:
    if not blob:
        return None
    raw = bytes(blob)
    count = len(raw) // 4
    if count <= 0 or count * 4 != len(raw):
        return None
    return struct.unpack(f"<{count}f", raw)


class KnowledgeIndex:
    """One SQLite file for one user's documents."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        _restrict(self.path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def replace_document(
        self,
        *,
        doc_id: str,
        filename: str,
        source_path: str,
        method: str,
        texts: list[str],
        embeddings: list[list[float]] | None,
    ) -> None:
        if embeddings is not None and len(embeddings) != len(texts):
            raise ValueError("embeddings and passages must have the same length")
        rows: list[tuple[str, str, int, str, bytes | None]] = []
        for ordinal, text in enumerate(texts):
            vector = embeddings[ordinal] if embeddings is not None else None
            rows.append((f"{doc_id}:{ordinal}", doc_id, ordinal, text, _pack(vector)))
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT doc_id FROM documents WHERE source_path = ?",
                (source_path,),
            ).fetchall()
            for record in existing:
                previous = str(record["doc_id"])
                conn.execute("DELETE FROM chunks WHERE doc_id = ?", (previous,))
                conn.execute("DELETE FROM documents WHERE doc_id = ?", (previous,))
            conn.execute(
                "INSERT INTO documents(doc_id, filename, source_path, added_at, method) VALUES (?, ?, ?, ?, ?)",
                (doc_id, filename, source_path, _now(), method),
            )
            conn.executemany(
                "INSERT INTO chunks(chunk_id, doc_id, ordinal, text, embedding) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        _restrict(self.path)

    def delete(self, doc_id: str) -> bool:
        with self._connect() as conn:
            found = conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
            if found is None:
                return False
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        return True

    def list_documents(self) -> list[DocumentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.doc_id, d.filename, d.source_path, d.added_at, d.method,
                       COUNT(c.chunk_id) AS passages
                FROM documents d
                LEFT JOIN chunks c ON c.doc_id = d.doc_id
                GROUP BY d.doc_id
                ORDER BY d.added_at, d.filename
                """
            ).fetchall()
        return [
            DocumentRecord(
                doc_id=str(row["doc_id"]),
                filename=str(row["filename"]),
                source_path=str(row["source_path"]),
                added_at=str(row["added_at"]),
                method=str(row["method"]),
                passages=int(row["passages"]),
            )
            for row in rows
        ]

    def chunks(self) -> list[ChunkRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.doc_id, d.filename, c.ordinal, c.text, c.embedding
                FROM chunks c
                JOIN documents d ON d.doc_id = c.doc_id
                ORDER BY d.filename, c.ordinal
                """
            ).fetchall()
        return [
            ChunkRecord(
                chunk_id=str(row["chunk_id"]),
                doc_id=str(row["doc_id"]),
                filename=str(row["filename"]),
                ordinal=int(row["ordinal"]),
                text=str(row["text"]),
                embedding=_unpack(row["embedding"]),
            )
            for row in rows
        ]


def _restrict(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        return
