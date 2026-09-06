"""Tamper-evident append-only runtime facts for session recovery and audit."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tool_system.audit import redact

_LOCK = threading.RLock()
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def event_log_dir() -> Path:
    path = Path.home() / ".clawd" / "events"
    path.mkdir(parents=True, exist_ok=True)
    return path


def event_log_path(session_id: str) -> Path:
    safe = _SAFE_ID.sub("", str(session_id or ""))[:160]
    if not safe:
        raise ValueError("session_id is required")
    return event_log_dir() / f"{safe}.jsonl"


def _hash(row: dict[str, Any]) -> str:
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _last_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return str(json.loads(lines[-1]).get("event_hash") or "") if lines else ""
    except (OSError, json.JSONDecodeError):
        return ""


def append_runtime_event(session_id: str, event_type: str, payload: dict[str, Any] | None = None, *,
                         job_id: str = "", workspace: str = "") -> dict[str, Any]:
    """Append one redacted fact; existing records are never rewritten."""
    target = event_log_path(session_id)
    with _LOCK:
        body = {
            "event_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": str(session_id),
            "job_id": str(job_id or ""),
            "type": str(event_type or "event"),
            "workspace": str(workspace or ""),
            "payload": redact(dict(payload or {})),
            "previous_hash": _last_hash(target),
        }
        body["event_hash"] = _hash(body)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, default=str) + "\n")
        return body


def read_runtime_events(session_id: str, limit: int = 500) -> dict[str, Any]:
    target = event_log_path(session_id)
    if not target.is_file():
        return {"session_id": session_id, "events": [], "valid_chain": True, "path": str(target)}
    with _LOCK:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    events: list[dict[str, Any]] = []
    expected_previous = ""
    valid = True
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            valid = False
            continue
        claimed = str(row.pop("event_hash", ""))
        if str(row.get("previous_hash") or "") != expected_previous or _hash(row) != claimed:
            valid = False
        row["event_hash"] = claimed
        expected_previous = claimed
        events.append(row)
    bounded = max(1, min(int(limit), 5000))
    return {"session_id": session_id, "events": events[-bounded:], "event_count": len(events),
            "valid_chain": valid, "path": str(target)}

