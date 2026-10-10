"""Durable Jonathan Ai memory, separate from any one chat thread.

Facts and a compact conversation index live in a SQLite file under
~/.clawd/memory. The file stays on this machine. Rows are scoped to the
current user, so one local database does not leak another user's notes.

This store follows Octop's long-term memory idea (extract facts from a
chat, recall them later, SQLite on disk) without the upstream graph,
vector index, or networked extractor. Storage uses the stdlib sqlite3
module only.

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop
SPDX-License-Identifier: MIT

Secrets are masked before they are written. Python 3.10 compatible:
no 3.11-only datetime or enum APIs.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from src.secret_mask import mask_secrets

MAX_FACTS = 80
MAX_INDEX = 40
MAX_FACT_CHARS = 240
MAX_SUMMARY_CHARS = 180
MAX_BRIEF_CHARS = 1600

_SECRET_RE = re.compile(
    r"(?i)\b(sk-[a-z0-9_\-]{8,}|ghp_[a-z0-9]{8,}|glpat-[a-z0-9\-_]{8,}|xox[baprs]-[a-z0-9-]{8,}|api[_-]?key\s*[:=]\s*\S+|bearer\s+[a-z0-9._\-]+)\b"
)
_SPOKEN_SECRET_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|api[ _-]?key|secret(?:[ _-]?key)?|access[ _-]?token|token)\s+is\s+\S+"
)
_REMEMBER_RE = re.compile(
    r"(?i)\b(?:please\s+)?remember(?:\s+that|\s+this)?[:\s]+(.+)"
)
_NAME_RE = re.compile(r"(?i)\bmy name is\s+([^\n.]+)")
_PREFER_RE = re.compile(r"(?i)\bi (?:prefer|use|work at|live in|am building)\s+([^\n.]+)")
_USER_ID_RE = re.compile(r"[^A-Za-z0-9_.-]")

_LOCK = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    source_session TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, id)
);

CREATE INDEX IF NOT EXISTS idx_facts_user_created
    ON facts (user_id, created_at);

CREATE TABLE IF NOT EXISTS conversations (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
    ON conversations (user_id, updated_at);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_MEMORY_USAGE = (
    "Usage: /memory list | /memory recall <text> | /memory delete <id>\n"
    "Memories are stored on this machine for the current user only."
)


def memory_dir() -> Path:
    path = Path.home() / ".clawd" / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_db_path() -> Path:
    """SQLite file for the current user, under this machine's home directory."""
    return memory_dir() / f"memory-{current_user_id()}.sqlite"


def _legacy_marker_path() -> Path:
    return memory_dir() / "json_imported"


def current_user_id() -> str:
    """Stable local user key. Override with JONATHAN_USER for a named profile.

    The key is only a row scope inside the local database. It is not sent
    anywhere.
    """
    raw = os.environ.get("JONATHAN_USER", "").strip()
    if not raw:
        try:
            raw = getpass.getuser()
        except Exception:
            raw = ""
    cleaned = _USER_ID_RE.sub("_", raw).strip("._-")
    return (cleaned or "local")[:64]


def _facts_path() -> Path:
    return memory_dir() / "facts.json"


def _index_path() -> Path:
    return memory_dir() / "index.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


def _mask_only(text: str) -> str:
    masked = _SPOKEN_SECRET_RE.sub("[redacted]", str(text or ""))
    masked = _SECRET_RE.sub("[redacted]", masked)
    return mask_secrets(masked)


def sanitize_memory_text(text: str, *, limit: int = MAX_FACT_CHARS) -> str:
    cleaned = " ".join(_mask_only(text).split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3] + "..."
    return cleaned.strip()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(memory_db_path()), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def _fact_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "text": row["text"],
        "source_session": row["source_session"],
        "created_at": row["created_at"],
    }


def _conversation_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "title": row["title"],
        "summary": row["summary"],
        "updated_at": row["updated_at"],
    }


def _trim_facts(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute(
        """
        DELETE FROM facts
        WHERE user_id = ?
          AND rowid NOT IN (
              SELECT rowid FROM facts
              WHERE user_id = ?
              ORDER BY created_at DESC, rowid DESC
              LIMIT ?
          )
        """,
        (user_id, user_id, MAX_FACTS),
    )


def _trim_conversations(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute(
        """
        DELETE FROM conversations
        WHERE user_id = ?
          AND rowid NOT IN (
              SELECT rowid FROM conversations
              WHERE user_id = ?
              ORDER BY updated_at DESC, rowid DESC
              LIMIT ?
          )
        """,
        (user_id, user_id, MAX_INDEX),
    )


def _import_legacy_json(conn: sqlite3.Connection) -> str | None:
    """Copy the old JSON store once, into the user who opens it first.

    Returns the user id that should be recorded in the legacy marker after
    the transaction commits. The marker is not written here, so a rollback
    can retry the import.
    """
    marker = _legacy_marker_path()
    if marker.exists():
        return None
    existing = conn.execute(
        "SELECT value FROM meta WHERE key = ?",
        ("json_imported",),
    ).fetchone()
    if existing is not None:
        return str(existing["value"] or current_user_id())
    user_id = current_user_id()
    seen: set[str] = set()
    facts_doc = _read_json(_facts_path(), {"facts": []})
    rows = facts_doc.get("facts")
    if isinstance(rows, list):
        for item in rows[-MAX_FACTS:]:
            if not isinstance(item, dict):
                continue
            text = sanitize_memory_text(str(item.get("text") or ""))
            if len(text) < 4:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            raw_id = str(item.get("id") or uuid.uuid4().hex[:12])
            fact_id = re.sub(r"[^A-Za-z0-9_-]", "", raw_id)[:32] or uuid.uuid4().hex[:12]
            created = str(item.get("created_at") or datetime.now().isoformat())[:40]
            source = sanitize_memory_text(str(item.get("source_session") or ""), limit=200)
            conn.execute(
                """
                INSERT OR IGNORE INTO facts (id, user_id, text, source_session, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (fact_id, user_id, text, source, created),
            )
    index_doc = _read_json(_index_path(), {"conversations": []})
    conversations = index_doc.get("conversations")
    if isinstance(conversations, list):
        for item in conversations[:MAX_INDEX]:
            if not isinstance(item, dict):
                continue
            session_id = sanitize_memory_text(str(item.get("session_id") or ""), limit=80)
            if not session_id:
                continue
            title = sanitize_memory_text(str(item.get("title") or ""), limit=72) or "New chat"
            summary = sanitize_memory_text(str(item.get("summary") or ""), limit=MAX_SUMMARY_CHARS)
            updated = str(item.get("updated_at") or datetime.now().isoformat())[:40]
            conn.execute(
                """
                INSERT INTO conversations (user_id, session_id, title, summary, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, session_id) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (user_id, session_id, title, summary, updated),
            )
    _trim_facts(conn, user_id)
    _trim_conversations(conn, user_id)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        ("json_imported", user_id),
    )
    return user_id


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    with _LOCK:
        conn = _connect()
        marker_user: str | None = None
        try:
            _ensure_schema(conn)
            marker_user = _import_legacy_json(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            marker_user = None
            raise
        finally:
            conn.close()
        if marker_user:
            _legacy_marker_path().write_text(marker_user + "\n", encoding="utf-8")


def list_facts() -> list[dict[str, Any]]:
    user_id = current_user_id()
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT id, text, source_session, created_at
            FROM facts
            WHERE user_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (user_id,),
        ).fetchall()
    return [_fact_from_row(row) for row in rows]


def list_memories() -> list[dict[str, Any]]:
    """Facts stored for the current user, oldest first."""
    rows: list[dict[str, Any]] = []
    for fact in list_facts():
        item = dict(fact)
        item["kind"] = "fact"
        rows.append(item)
    return rows


def add_fact(text: str, *, source_session: str = "") -> dict[str, Any] | None:
    cleaned = sanitize_memory_text(text)
    if len(cleaned) < 4:
        return None
    user_id = current_user_id()
    source = sanitize_memory_text(source_session, limit=200)
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT id, text, source_session, created_at
            FROM facts
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
        lowered = cleaned.lower()
        for row in rows:
            if str(row["text"] or "").strip().lower() == lowered:
                return _fact_from_row(row)
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": cleaned,
            "source_session": source,
            "created_at": datetime.now().isoformat(),
        }
        conn.execute(
            """
            INSERT INTO facts (id, user_id, text, source_session, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item["id"], user_id, item["text"], item["source_session"], item["created_at"]),
        )
        _trim_facts(conn, user_id)
    return item


def delete_memory(memory_id: str) -> bool:
    """Delete one fact for the current user. Other users are left untouched."""
    fact_id = str(memory_id or "").strip()
    if not fact_id:
        return False
    user_id = current_user_id()
    with _db() as conn:
        cursor = conn.execute(
            "DELETE FROM facts WHERE user_id = ? AND id = ?",
            (user_id, fact_id),
        )
        return cursor.rowcount > 0


def recall(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Find this user's facts that contain the query.

    Matching uses SQLite LIKE so recall does not depend on FTS5 being
    compiled into the local sqlite build.
    """
    cleaned = sanitize_memory_text(query, limit=120)
    if len(cleaned) < 2:
        return []
    needle = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{needle}%"
    user_id = current_user_id()
    bounded = max(1, min(int(limit), MAX_FACTS))
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT id, text, source_session, created_at
            FROM facts
            WHERE user_id = ? AND text LIKE ? ESCAPE '\\'
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (user_id, pattern, bounded),
        ).fetchall()
    return [_fact_from_row(row) for row in rows]


def list_conversation_index() -> list[dict[str, Any]]:
    user_id = current_user_id()
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT session_id, title, summary, updated_at
            FROM conversations
            WHERE user_id = ?
            ORDER BY updated_at DESC, rowid DESC
            """,
            (user_id,),
        ).fetchall()
    return [_conversation_from_row(row) for row in rows]


def upsert_conversation_index(
    *,
    session_id: str,
    title: str,
    summary: str,
) -> dict[str, Any]:
    user_id = current_user_id()
    item = {
        "session_id": sanitize_memory_text(session_id, limit=80) or "session",
        "title": sanitize_memory_text(title, limit=72) or "New chat",
        "summary": sanitize_memory_text(summary, limit=MAX_SUMMARY_CHARS),
        "updated_at": datetime.now().isoformat(),
    }
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO conversations (user_id, session_id, title, summary, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, session_id) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                updated_at = excluded.updated_at
            """,
            (user_id, item["session_id"], item["title"], item["summary"], item["updated_at"]),
        )
        _trim_conversations(conn, user_id)
    return item


def extract_facts(user_text: str) -> list[str]:
    text = str(user_text or "").strip()
    if not text:
        return []
    found: list[str] = []
    for match in _REMEMBER_RE.finditer(text):
        found.append(match.group(1))
    name = _NAME_RE.search(text)
    if name:
        found.append(f"User's name is {name.group(1).strip()}")
    prefer = _PREFER_RE.search(text)
    if prefer:
        found.append(f"User {prefer.group(0).strip()}")
    return [sanitize_memory_text(item) for item in found if sanitize_memory_text(item)]


def remember_turn(
    *,
    session_id: str,
    title: str,
    user_text: str,
    assistant_text: str = "",
) -> dict[str, Any]:
    """Record implicit facts and a compact index entry after a chat turn."""
    added: list[dict[str, Any]] = []
    for fact in extract_facts(user_text):
        item = add_fact(fact, source_session=session_id)
        if item:
            added.append(item)
    user_line = sanitize_memory_text(user_text.splitlines()[0] if user_text else "", limit=90)
    assistant_line = sanitize_memory_text(
        (assistant_text or "").splitlines()[0] if assistant_text else "",
        limit=90,
    )
    summary = user_line
    if assistant_line:
        summary = f"{user_line} → {assistant_line}".strip(" →")
    index_item = upsert_conversation_index(session_id=session_id, title=title, summary=summary)
    return {"facts": added, "index": index_item}


def build_memory_brief(*, exclude_session_id: str | None = None) -> str:
    """Short system-prompt brief: shared facts + other-chat titles/summaries."""
    facts = list_facts()
    others = list_conversation_index()
    if exclude_session_id:
        others = [row for row in others if row.get("session_id") != exclude_session_id]
    if not facts and not others:
        return ""
    lines = [
        "## Jonathan Ai memory",
        "These notes persist across chats. Threads stay isolated; use this only when relevant.",
        "Do not invent extra agents. Do not repeat secrets.",
    ]
    if facts:
        lines.append("### Facts")
        for fact in facts[-24:]:
            text = str(fact.get("text") or "").strip()
            if text:
                lines.append(f"- {text}")
    if others:
        lines.append("### Other conversations (titles/summaries only)")
        for row in others[:12]:
            title = str(row.get("title") or "New chat").strip()
            summary = str(row.get("summary") or "").strip()
            if summary:
                lines.append(f"- {title}: {summary}")
            else:
                lines.append(f"- {title}")
    brief = "\n".join(lines)
    if len(brief) > MAX_BRIEF_CHARS:
        brief = brief[: MAX_BRIEF_CHARS - 3] + "..."
    return brief


def format_memory_list() -> str:
    rows = list_memories()
    user = current_user_id()
    header = f"Local memories for {user} ({memory_db_path()}):"
    if not rows:
        return header + "\n\nNo memories stored."
    lines = [header, ""]
    for row in rows:
        lines.append(f"  {row['id']}  {row['text']}")
    lines.append("")
    lines.append("Delete one with: /memory delete <id>")
    return "\n".join(lines)


def format_memory_recall(query: str) -> str:
    rows = recall(query)
    if not rows:
        return "No matching memories."
    lines = ["Matching memories:", ""]
    for row in rows:
        lines.append(f"  {row['id']}  {row['text']}")
    return "\n".join(lines)


def format_memory_delete(memory_id: str) -> str:
    fact_id = str(memory_id or "").strip()
    if delete_memory(fact_id):
        return f"Deleted memory {fact_id}."
    return f"No memory with id {fact_id} for this user."


def format_memory_command(args: str) -> str:
    """Render /memory list, recall, or delete for the current user."""
    parts = (args or "").strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    rest = parts[1].strip() if len(parts) > 1 else ""
    if action in {"list", "ls"}:
        return format_memory_list()
    if action in {"delete", "rm", "forget"}:
        if not rest:
            return "Usage: /memory delete <id>"
        return format_memory_delete(rest.split()[0])
    if action in {"recall", "search", "find"}:
        if not rest:
            return "Usage: /memory recall <text>"
        return format_memory_recall(rest)
    return _MEMORY_USAGE
