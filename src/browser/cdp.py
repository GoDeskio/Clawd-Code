"""Direct Chrome DevTools Protocol control.

The websocket client is imported only when a real browser is attached.
Tests pass a fake transport and never open a socket.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Callable, Protocol

from .profile import chrome_launch_command, profile_dir, profile_port
from .sources import BROWSER_EXTRA_HINT, BrowserError

Send = Callable[[str, dict[str, Any] | None], dict[str, Any]]


class BrowserTransport(Protocol):
    def connect(self, data_dir: Path, port: int) -> None:
        """Attach to the page target for this profile."""

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one CDP command and return the result object."""

    def close(self) -> None:
        """Detach. The profile directory stays on disk."""


def find_local_chrome() -> str | None:
    """Return a Chrome or Chromium binary already installed on this machine."""
    import os

    override = (os.environ.get("JONATHAN_CHROME") or "").strip()
    names = (
        override,
        shutil.which("google-chrome") or "",
        shutil.which("google-chrome-stable") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    for candidate in names:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class LocalChromeTransport:
    """Launch Chrome with a persistent profile and speak CDP on localhost."""

    def __init__(self, binary: str | None = None, opener: Any = None) -> None:
        self.binary = binary
        self._opener = opener or urllib.request.urlopen
        self._ws: Any = None
        self._next_id = 0
        self._process: Any = None

    def connect(self, data_dir: Path, port: int) -> None:
        binary = self.binary or find_local_chrome()
        if not binary:
            raise BrowserError(
                "Chrome or Chromium was not found. Install Google Chrome, or download "
                "Chrome for Testing from the official source. Jonathan Ai does not use npmmirror."
            )
        command = chrome_launch_command(binary, data_dir, port)
        import subprocess

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        targets = self._read_targets(port)
        page = next((item for item in targets if item.get("type") == "page"), None)
        if page is None or not page.get("webSocketDebuggerUrl"):
            raise BrowserError("Chrome did not expose a local page target.")
        socket_url = str(page["webSocketDebuggerUrl"])
        if not socket_url.startswith("ws://127.0.0.1:") and not socket_url.startswith("ws://localhost:"):
            raise BrowserError("Refusing a CDP socket that is not on localhost.")
        websocket = _load_websocket()
        self._ws = websocket.create_connection(socket_url, timeout=10, suppress_origin=True)

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise BrowserError("The browser is not connected.")
        self._next_id += 1
        payload = {"id": self._next_id, "method": method, "params": params or {}}
        self._ws.send(json.dumps(payload))
        raw = self._ws.recv()
        message = json.loads(raw)
        if "error" in message:
            detail = message["error"]
            raise BrowserError(str(detail.get("message") if isinstance(detail, dict) else detail))
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._process is not None:
            self._process.terminate()
            self._process = None

    def _read_targets(self, port: int) -> list[dict[str, Any]]:
        with self._opener(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
            body = response.read()
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, list):
            raise BrowserError("Chrome target list was not a list.")
        return [item for item in data if isinstance(item, dict)]


def _load_websocket():
    try:
        import websocket
    except ImportError as exc:
        raise BrowserError(BROWSER_EXTRA_HINT) from exc
    return websocket


def attach_profile(name: str, transport: BrowserTransport, root: Path | None = None) -> Path:
    """Open ``name`` without deleting an existing profile directory."""
    data_dir = profile_dir(name, root)
    transport.connect(data_dir, profile_port(data_dir))
    return data_dir
