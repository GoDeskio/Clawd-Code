"""Persistent Chrome profiles so logins survive a restart.

Each profile is a Chrome ``user-data-dir`` under the user's home directory.
Closing a session does not delete it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .sources import BrowserError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PORT_START = 9222


def browser_root() -> Path:
    return Path.home() / ".clawd" / "browser" / "profiles"


def _user_id() -> str:
    from ..agent.memory import current_user_id

    return current_user_id()


def profiles_root(root: Path | None = None) -> Path:
    base = root if root is not None else browser_root()
    path = base / _user_id()
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_dir(name: str, root: Path | None = None) -> Path:
    """Return the persistent user-data directory for ``name``."""
    cleaned = str(name or "default").strip() or "default"
    if _NAME_RE.fullmatch(cleaned) is None:
        raise BrowserError("Profile name must be letters, numbers, dot, dash, or underscore.")
    path = profiles_root(root) / cleaned
    path.mkdir(parents=True, exist_ok=True)
    marker = path / ".jonathan-browser-profile"
    if not marker.is_file():
        marker.write_text(json.dumps({"name": cleaned}), encoding="utf-8")
    return path


def profile_port(path: Path) -> int:
    """Stable localhost CDP port stored beside the profile."""
    port_file = path / "cdp-port"
    if port_file.is_file():
        try:
            saved = int(port_file.read_text(encoding="utf-8").strip())
        except ValueError:
            saved = 0
        if 1024 <= saved <= 65535:
            return saved
    used = set()
    parent = path.parent
    if parent.is_dir():
        for child in parent.iterdir():
            candidate = child / "cdp-port"
            if candidate.is_file():
                try:
                    used.add(int(candidate.read_text(encoding="utf-8").strip()))
                except ValueError:
                    continue
    port = _PORT_START
    while port in used:
        port += 1
    port_file.write_text(str(port), encoding="utf-8")
    return port


def chrome_launch_command(binary: str, data_dir: Path, port: int) -> list[str]:
    """Arguments for a real Chrome or Chromium process with a persistent profile."""
    if not binary or not str(binary).strip():
        raise BrowserError("Chrome or Chromium was not found on this machine.")
    return [
        str(binary),
        f"--user-data-dir={data_dir}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
    ]
