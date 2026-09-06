"""Durable Jonathan Ai memory, separate from any one chat thread.

Facts and a compact conversation index live under ~/.clawd/memory.
They are never written into git or installer artifacts.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Retain durable knowledge and conversation metadata instead of silently
# forgetting older projects. Prompt injection still uses a small relevant tail.
MAX_FACTS = 5000
MAX_INDEX = 10000
MAX_FACT_CHARS = 240
MAX_SUMMARY_CHARS = 180
MAX_BRIEF_CHARS = 1600
_MEMORY_LOCK = threading.RLock()

_SECRET_RE = re.compile(
    r"(?i)\b(sk-[a-z0-9_\-]{8,}|ghp_[a-z0-9]{8,}|glpat-[a-z0-9\-_]{8,}|xox[baprs]-[a-z0-9-]{8,}|api[_-]?key\s*[:=]\s*\S+|bearer\s+[a-z0-9._\-]+)\b"
)
_REMEMBER_RE = re.compile(
    r"(?i)\b(?:please\s+)?remember(?:\s+that|\s+this)?[:\s]+(.+)"
)
_NAME_RE = re.compile(r"(?i)\bmy name is\s+([^\n.]+)")
_PREFER_RE = re.compile(r"(?i)\bi (?:prefer|use|work at|live in|am building)\s+([^\n.]+)")


def memory_dir() -> Path:
    path = Path.home() / ".clawd" / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def sanitize_memory_text(text: str, *, limit: int = MAX_FACT_CHARS) -> str:
    cleaned = " ".join(str(text or "").split())
    cleaned = _SECRET_RE.sub("[redacted]", cleaned)
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3] + "..."
    return cleaned.strip()


def list_facts() -> list[dict[str, Any]]:
    with _MEMORY_LOCK:
        data = _read_json(_facts_path(), {"facts": []})
        rows = data.get("facts")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def add_fact(text: str, *, source_session: str = "") -> dict[str, Any] | None:
    cleaned = sanitize_memory_text(text)
    if len(cleaned) < 4:
        return None
    with _MEMORY_LOCK:
        facts = list_facts()
        lowered = cleaned.lower()
        for existing in facts:
            if str(existing.get("text") or "").strip().lower() == lowered:
                return existing
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": cleaned,
            "source_session": source_session,
            "created_at": datetime.now().isoformat(),
        }
        facts.append(item)
        _write_json(_facts_path(), {"facts": facts[-MAX_FACTS:]})
        return item


def list_conversation_index() -> list[dict[str, Any]]:
    with _MEMORY_LOCK:
        data = _read_json(_index_path(), {"conversations": []})
        rows = data.get("conversations")
        items = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        items.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
        return items


def upsert_conversation_index(
    *,
    session_id: str,
    title: str,
    summary: str,
) -> dict[str, Any]:
    with _MEMORY_LOCK:
        item = {
            "session_id": session_id,
            "title": sanitize_memory_text(title, limit=72) or "New chat",
            "summary": sanitize_memory_text(summary, limit=MAX_SUMMARY_CHARS),
            "updated_at": datetime.now().isoformat(),
        }
        rows = [row for row in list_conversation_index() if row.get("session_id") != session_id]
        rows.insert(0, item)
        _write_json(_index_path(), {"conversations": rows[:MAX_INDEX]})
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
