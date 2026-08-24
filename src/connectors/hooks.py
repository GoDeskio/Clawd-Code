"""Documented hooks so other agents can call Jonathan Ai, and vice versa.

Cursor / Codex / local agents are not invented here. The user points Jonathan Ai
at a real endpoint they already run, or drops a hook file.

Hook file (optional): ~/.clawd/hooks/cursor.json
{
  "name": "Cursor",
  "base_url": "http://127.0.0.1:PORT/v1",
  "api_key": ""
}

Inbound: other local tools POST http://127.0.0.1:8765/api/hooks/inbound
with header X-Clawd-Token and JSON { "text": "..." }.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .store import save_agent


def hooks_dir(home: Path | None = None) -> Path:
    root = Path(home) if home is not None else Path.home()
    return root / ".clawd" / "hooks"


def load_hook_files(home: Path | None = None) -> list[dict[str, Any]]:
    folder = hooks_dir(home)
    if not folder.is_dir():
        return []
    loaded: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("base_url"):
            continue
        name = str(data.get("name") or path.stem)
        save_agent(
            name=name,
            base_url=str(data["base_url"]),
            api_key=str(data.get("api_key") or ""),
            kind=str(data.get("kind") or path.stem),
        )
        loaded.append({"name": name, "path": str(path)})
    return loaded
