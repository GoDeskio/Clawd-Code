from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_SECRET_KEYS = re.compile(r"(?i)(api.?key|token|secret|password|authorization|credential)")
_URL_CREDENTIALS = re.compile(r"(https?://)[^/@:\s]+:[^/@\s]+@", re.IGNORECASE)
_INLINE_SECRET = re.compile(r"(?i)\b(sk-[a-z0-9_\-]{8,}|ghp_[a-z0-9]{8,}|glpat-[a-z0-9\-_]{8,}|bearer\s+[a-z0-9._\-]+)\b")


def audit_path() -> Path:
    return Path.home() / ".clawd" / "audit" / "actions.jsonl"


def redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEYS.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    safe = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
    if isinstance(safe, str):
        safe = _URL_CREDENTIALS.sub(r"\1[redacted]@", safe)
        safe = _INLINE_SECRET.sub("[redacted]", safe)
        if len(safe) > 4000:
            return safe[:3997] + "..."
    return safe


def record_action(entry: dict[str, Any]) -> dict[str, Any]:
    row = {"timestamp": datetime.now(timezone.utc).isoformat(), **redact(entry)}
    target = audit_path()
    with _LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def read_actions(limit: int = 200, *, tool: str = "", session_id: str = "") -> list[dict[str, Any]]:
    target = audit_path()
    if not target.exists():
        return []
    with _LOCK:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if tool and str(row.get("tool") or "").lower() != tool.lower():
            continue
        if session_id and str(row.get("session_id") or "") != session_id:
            continue
        rows.append(row)
        if len(rows) >= max(1, min(5000, int(limit))):
            break
    return rows
