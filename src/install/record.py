"""Persist install location so the running app uses the Jonathan tree."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import CANONICAL_HTTPS, INSTALL_RECORD_NAME


def install_record_path(home: Path | None = None) -> Path:
    root = Path(home) if home is not None else Path.home()
    return root / ".clawd" / INSTALL_RECORD_NAME


def write_install_record(
    *,
    source_dir: Path,
    venv_python: Path,
    commit: str = "",
    branch: str = "",
    home: Path | None = None,
) -> Path:
    path = install_record_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_dir": str(Path(source_dir).expanduser().resolve()),
        "venv_python": str(Path(venv_python).expanduser().resolve()),
        "repo": CANONICAL_HTTPS,
        "commit": commit,
        "branch": branch,
        "updated_at": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_install_record(home: Path | None = None) -> dict[str, Any] | None:
    path = install_record_path(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_source_dir(explicit: str | Path | None = None, home: Path | None = None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser().resolve()
    record = read_install_record(home)
    if record and record.get("source_dir"):
        return Path(str(record["source_dir"])).expanduser().resolve()
    return None
