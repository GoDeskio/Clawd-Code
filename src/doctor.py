"""Fast, side-effect-free diagnostics plus safe local repairs."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from src.agent.checkpoints import checkpoint_dir
from src.agent.history_search import rebuild_history_index, search_database_path
from src.agent.memory import memory_dir
from src.agent.session import session_dir
from src.config import get_default_provider, has_configured_provider
from src.tool_system.tools.terminal import discover_terminals


def _check(name: str, ok: bool, detail: str, repairable: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "repairable": repairable}


def run_doctor(*, repair: bool = False) -> dict[str, Any]:
    repaired: list[str] = []
    if repair:
        for folder in (session_dir(), memory_dir(), checkpoint_dir()):
            folder.mkdir(parents=True, exist_ok=True)
        rebuild_history_index()
        repaired.extend(["state directories", "history search index"])
    required = ["anthropic", "openai", "PIL", "psutil", "trimesh"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    state_root = Path.home() / ".clawd"
    writable = state_root.exists() and os.access(state_root, os.W_OK)
    try:
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        fts = True
    except sqlite3.OperationalError:
        fts = False
    terminals = discover_terminals()
    checks = [
        _check("Python", sys.version_info >= (3, 10), sys.version.split()[0]),
        _check("Python dependencies", not missing, "ready" if not missing else "missing: " + ", ".join(missing), bool(missing)),
        _check("Persistent state", writable, str(state_root), True),
        _check("Conversation search", fts, f"FTS5 · {search_database_path()}" if fts else "SQLite FTS5 unavailable"),
        _check("Model provider", has_configured_provider(), get_default_provider(), False),
        _check("Git", bool(shutil.which("git")), shutil.which("git") or "not found"),
        _check("Node.js", bool(shutil.which("node")), shutil.which("node") or "optional / not found"),
        _check("Ripgrep", bool(shutil.which("rg")), shutil.which("rg") or "optional / not found"),
        _check("FFmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "optional / not found"),
        _check("Terminal backends", bool(terminals), ", ".join(str(row.get("name") or row.get("shell") or "terminal") for row in terminals) or "none"),
    ]
    required_checks = checks[:6]
    return {
        "ok": all(row["ok"] for row in required_checks),
        "checks": checks,
        "repaired": repaired,
        "next_action": "Connect a model provider." if not has_configured_provider() else ("Run repair." if missing or not writable else "Ready."),
    }

