"""Persistent named agent profiles and local agent-to-agent mailboxes."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_NAME = re.compile(r"^[^\x00-\x1f]{1,60}$")


def roster_path() -> Path:
    path = Path.home() / ".clawd" / "agent_profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> dict[str, Any]:
    path = roster_path()
    if not path.exists():
        return {"version": 1, "agents": [], "messages": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"version": 1, "agents": [], "messages": []}
    return data if isinstance(data, dict) else {"version": 1, "agents": [], "messages": []}


def _save(data: dict[str, Any]) -> None:
    path = roster_path()
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def list_agents() -> list[dict[str, Any]]:
    with _LOCK:
        rows = [dict(row) for row in _load().get("agents", []) if isinstance(row, dict)]
    rows.sort(key=lambda row: str(row.get("name") or "").lower())
    return rows


def get_agent(agent_id: str) -> dict[str, Any] | None:
    return next((row for row in list_agents() if row.get("id") == agent_id), None)


def save_agent(payload: dict[str, Any], *, canonical_session_id: str | None = None) -> dict[str, Any]:
    name = " ".join(str(payload.get("name") or "").split())
    if not _NAME.fullmatch(name):
        raise ValueError("Agent name must be 1-60 printable characters.")
    instructions = str(payload.get("instructions") or payload.get("role") or "").strip()
    if not instructions:
        raise ValueError("Agent instructions are required.")
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        data = _load()
        agents = [row for row in data.get("agents", []) if isinstance(row, dict)]
        agent_id = str(payload.get("id") or "").strip()
        existing = next((row for row in agents if row.get("id") == agent_id), None) if agent_id else None
        if existing is None:
            agent_id = uuid.uuid4().hex[:12]
            existing = {"id": agent_id, "created_at": now}
            agents.append(existing)
        existing.update({
            "name": name,
            "instructions": instructions[:12_000],
            "workspace": str(payload.get("workspace") or existing.get("workspace") or ""),
            "provider": str(payload.get("provider") or existing.get("provider") or ""),
            "model": str(payload.get("model") or existing.get("model") or ""),
            "avatar": str(payload.get("avatar") or existing.get("avatar") or "robot"),
            "canonical_session_id": str(canonical_session_id or existing.get("canonical_session_id") or ""),
            "updated_at": now,
        })
        data["agents"] = agents
        data.setdefault("messages", [])
        _save(data)
        return dict(existing)


def remove_agent(agent_id: str) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        before = len(data.get("agents", []))
        data["agents"] = [row for row in data.get("agents", []) if isinstance(row, dict) and row.get("id") != agent_id]
        if len(data["agents"]) == before:
            raise ValueError("Agent profile not found.")
        # Conversation history is intentionally retained; only the roster entry is removed.
        _save(data)
    return {"removed": agent_id, "conversation_retained": True}


def send_message(*, sender_session_id: str, recipient_agent_id: str, text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("Message is empty.")
    if get_agent(recipient_agent_id) is None:
        raise ValueError("Recipient agent profile not found.")
    item = {
        "id": uuid.uuid4().hex[:12],
        "sender_session_id": sender_session_id,
        "recipient_agent_id": recipient_agent_id,
        "text": cleaned[:40_000],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_at": "",
    }
    with _LOCK:
        data = _load()
        messages = [row for row in data.get("messages", []) if isinstance(row, dict)]
        messages.append(item)
        data["messages"] = messages[-5000:]
        _save(data)
    return item


def read_inbox(agent_id: str, *, mark_read: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
        rows = [row for row in data.get("messages", []) if isinstance(row, dict) and row.get("recipient_agent_id") == agent_id]
        rows = rows[-max(1, min(limit, 200)):]
        if mark_read:
            now = datetime.now(timezone.utc).isoformat()
            ids = {row.get("id") for row in rows}
            for row in data.get("messages", []):
                if isinstance(row, dict) and row.get("id") in ids and not row.get("read_at"):
                    row["read_at"] = now
            _save(data)
        return [dict(row) for row in reversed(rows)]

