"""Local full-text search across durable Jonathan Ai conversations and memory."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from src.agent.memory import list_conversation_index, list_facts, memory_dir
from src.agent.session import Session, _message_text, session_dir

_LOCK = threading.RLock()


def search_database_path() -> Path:
    path = memory_dir() / "search.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(search_database_path(), timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=20000")
    return connection


def _source_stamp() -> str:
    paths = list(session_dir().glob("*.json")) + [memory_dir() / "facts.json", memory_dir() / "index.json"]
    parts: list[str] = []
    for path in sorted(paths):
        try:
            stat = path.stat()
        except OSError:
            continue
        parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def _current_index_metadata() -> dict[str, Any] | None:
    if not search_database_path().exists():
        return None
    try:
        with closing(_connect()) as db:
            rows = db.execute("SELECT key, value FROM history_meta").fetchall()
    except sqlite3.Error:
        return None
    meta = {str(row["key"]): str(row["value"]) for row in rows}
    if meta.get("source_stamp") != _source_stamp():
        return None
    return {
        "documents": int(meta.get("documents") or 0),
        "fts5": meta.get("fts5") == "1",
        "path": str(search_database_path()),
    }


def rebuild_history_index() -> dict[str, Any]:
    """Rebuild the compact search index from authoritative UTF-8 JSON state."""
    with _LOCK, closing(_connect()) as db:
        db.execute("DROP TABLE IF EXISTS history_fts")
        db.execute("DROP TABLE IF EXISTS history")
        db.execute("DROP TABLE IF EXISTS history_meta")
        db.execute("CREATE TABLE history_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute(
            "CREATE TABLE history (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
            "session_id TEXT NOT NULL, title TEXT NOT NULL, role TEXT NOT NULL, "
            "content TEXT NOT NULL, timestamp TEXT NOT NULL)"
        )
        fts = True
        try:
            db.execute(
                "CREATE VIRTUAL TABLE history_fts USING fts5(title, content, "
                "content='history', content_rowid='id', tokenize='unicode61')"
            )
        except sqlite3.OperationalError:
            fts = False
        rows: list[tuple[str, str, str, str, str, str]] = []
        for summary in Session.list_sessions():
            session_id = str(summary.get("session_id") or "")
            loaded = Session.load(session_id)
            if loaded is None:
                continue
            title = loaded.display_title()
            for message in loaded.conversation.messages:
                if getattr(message, "_is_internal", False):
                    continue
                content = _message_text(message.content).strip()
                if content:
                    rows.append(("message", session_id, title, message.role, content, message.timestamp or ""))
        for fact in list_facts():
            content = str(fact.get("text") or "").strip()
            if content:
                rows.append(("memory", str(fact.get("source_session") or ""), "Shared memory", "memory", content, str(fact.get("created_at") or "")))
        # Conversation summaries remain searchable even after a chat is hidden.
        for item in list_conversation_index():
            content = str(item.get("summary") or "").strip()
            if content:
                rows.append(("summary", str(item.get("session_id") or ""), str(item.get("title") or "Conversation"), "summary", content, str(item.get("updated_at") or "")))
        db.executemany(
            "INSERT INTO history(kind, session_id, title, role, content, timestamp) VALUES(?,?,?,?,?,?)",
            rows,
        )
        if fts:
            db.execute("INSERT INTO history_fts(rowid, title, content) SELECT id, title, content FROM history")
        db.executemany("INSERT INTO history_meta(key, value) VALUES(?,?)", [
            ("source_stamp", _source_stamp()), ("documents", str(len(rows))), ("fts5", "1" if fts else "0"),
        ])
        db.commit()
        return {"documents": len(rows), "fts5": fts, "path": str(search_database_path())}


def _fts_query(query: str) -> str:
    words = [word.strip('"\'()[]{}:*+-') for word in query.split()]
    return " AND ".join(f'"{word.replace(chr(34), chr(34) * 2)}"' for word in words if word)


def search_history(query: str, *, limit: int = 30) -> dict[str, Any]:
    cleaned = " ".join(str(query or "").split())
    if not cleaned:
        return {"query": "", "hits": [], **rebuild_history_index()}
    meta = _current_index_metadata() or rebuild_history_index()
    capped = max(1, min(int(limit), 100))
    with _LOCK, closing(_connect()) as db:
        if meta["fts5"]:
            sql = (
                "SELECT h.*, snippet(history_fts, 1, '[', ']', ' … ', 22) AS snippet "
                "FROM history_fts JOIN history h ON h.id=history_fts.rowid "
                "WHERE history_fts MATCH ? ORDER BY bm25(history_fts), h.timestamp DESC LIMIT ?"
            )
            try:
                found = db.execute(sql, (_fts_query(cleaned), capped)).fetchall()
            except sqlite3.OperationalError:
                found = []
        else:
            pattern = f"%{cleaned}%"
            found = db.execute(
                "SELECT h.*, content AS snippet FROM history h WHERE title LIKE ? OR content LIKE ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (pattern, pattern, capped),
            ).fetchall()
    hits = [dict(row) for row in found]
    for hit in hits:
        hit.pop("id", None)
        if not hit.get("snippet"):
            hit["snippet"] = str(hit.get("content") or "")[:240]
        hit.pop("content", None)
    return {"query": cleaned, "hits": hits, **meta}
