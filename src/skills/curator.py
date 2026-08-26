"""Recoverable lifecycle metadata for agent-authored skills."""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def _root() -> Path:
    from .library import user_skill_library

    return user_skill_library()


def _usage_path() -> Path:
    return _root() / ".usage.json"


def _load() -> dict[str, Any]:
    path = _usage_path()
    if not path.exists():
        return {"skills": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"skills": {}}
    return data if isinstance(data, dict) else {"skills": {}}


def _save(data: dict[str, Any]) -> None:
    path = _usage_path()
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def record_skill_use(name: str) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        skills = data.setdefault("skills", {})
        row = skills.setdefault(name, {"use_count": 0, "pinned": False, "state": "active"})
        row["use_count"] = int(row.get("use_count") or 0) + 1
        row["last_used_at"] = datetime.now(timezone.utc).isoformat()
        _save(data)
        return dict(row)


def report() -> list[dict[str, Any]]:
    data = _load().get("skills", {})
    rows = [{"name": name, **row} for name, row in data.items() if isinstance(row, dict)]
    rows.sort(key=lambda row: (not bool(row.get("pinned")), str(row.get("name") or "")))
    return rows


def pin(name: str, pinned: bool = True) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        row = data.setdefault("skills", {}).setdefault(name, {"use_count": 0, "state": "active"})
        row["pinned"] = bool(pinned)
        _save(data)
        return {"name": name, **row}


def archive(name: str) -> dict[str, Any]:
    source = _root() / name
    if not source.is_dir():
        raise ValueError("Only user skills can be archived, and this user skill was not found.")
    state = next((row for row in report() if row.get("name") == name), {})
    if state.get("pinned"):
        raise ValueError("Pinned skills cannot be archived. Unpin it first.")
    archive_root = _root() / ".archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    destination = archive_root / name
    if destination.exists():
        destination = archive_root / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(source), str(destination))
    with _LOCK:
        data = _load()
        row = data.setdefault("skills", {}).setdefault(name, {"use_count": 0})
        row.update({"state": "archived", "archived_at": datetime.now(timezone.utc).isoformat(), "archive_path": str(destination)})
        _save(data)
    return {"name": name, "archived": True, "path": str(destination), "recoverable": True}


def restore(name: str) -> dict[str, Any]:
    state = next((row for row in report() if row.get("name") == name), None)
    source = Path(str((state or {}).get("archive_path") or (_root() / ".archive" / name)))
    destination = _root() / name
    if not source.is_dir():
        raise ValueError("Archived skill was not found.")
    if destination.exists():
        raise ValueError("An active skill with this name already exists.")
    shutil.move(str(source), str(destination))
    with _LOCK:
        data = _load()
        row = data.setdefault("skills", {}).setdefault(name, {"use_count": 0})
        row.update({"state": "active", "restored_at": datetime.now(timezone.utc).isoformat(), "archive_path": ""})
        _save(data)
    return {"name": name, "restored": True, "path": str(destination)}
