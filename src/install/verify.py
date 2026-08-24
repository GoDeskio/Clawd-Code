"""Verify the installed tree can start a desktop session."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any


def verify_agent_session(source_dir: Path, *, python_path: Path | None = None) -> dict[str, Any]:
    """Import the agent from the installed tree and create a session.

    Does not call a provider. Success means the local runtime is importable
    and can open a session file — the last wizard step on a clean machine.
    """
    source_dir = Path(source_dir).resolve()
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
    session_mod = importlib.import_module("src.agent.session")
    runtime_mod = importlib.import_module("src.desktop.runtime")
    session = session_mod.Session.create("anthropic", "unconfigured", workspace=str(source_dir))
    runtime = runtime_mod.DesktopRuntime(workspace=source_dir)
    status = runtime.status()
    return {
        "ok": True,
        "session_id": session.session_id,
        "workspace": str(runtime.workspace),
        "needs_setup": status.get("needs_setup"),
        "source_dir": str(source_dir),
        "python": str(python_path or Path(sys.executable)),
    }
