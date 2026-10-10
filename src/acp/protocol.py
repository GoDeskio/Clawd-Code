"""Minimal ACP client over newline-delimited JSON-RPC on stdio.

The child process is the local runner. Jonathan Ai does not open a network
connection for this protocol.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]


class AcpError(RuntimeError):
    """The local runner failed or stopped speaking ACP."""


@dataclass
class AcpTurn:
    text: str = ""
    paths: list[str] = field(default_factory=list)


class AcpProcess:
    """One runner process for one coding task."""

    def __init__(
        self,
        argv: list[str],
        cwd: Path,
        *,
        on_progress: Progress | None = None,
        timeout_s: float = 120,
    ) -> None:
        if not argv or not argv[0].strip():
            raise AcpError("runner command is empty")
        self.argv = argv
        self.cwd = cwd
        self.timeout_s = timeout_s
        self._on_progress = on_progress
        self._proc: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._cv = threading.Condition()
        self._pending: dict[int, dict | None] = {}
        self._next_id = 0
        self._reader: threading.Thread | None = None
        self._closed = False
        self.turn = AcpTurn()

    def run(self, task: str) -> AcpTurn:
        self._proc = subprocess.Popen(
            self.argv,
            cwd=str(self.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, name="jonathan-acp", daemon=True)
        self._reader.start()
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "jonathan-ai", "version": "0.2.8"},
                },
            )
            created = self._request("session/new", {"cwd": str(self.cwd), "mcpServers": []})
            session_id = str(created.get("sessionId") or created.get("session_id") or "")
            if not session_id:
                raise AcpError("runner did not open a session")
            self._request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": task}],
                },
            )
            return self.turn
        finally:
            self.close()

    def close(self) -> None:
        proc = self._proc
        if proc is None or self._closed:
            return
        self._closed = True
        if proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

    def _request(self, method: str, params: dict) -> dict:
        with self._cv:
            self._next_id += 1
            msg_id = self._next_id
            self._pending[msg_id] = None
        self._write({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout_s
        with self._cv:
            while self._pending.get(msg_id) is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AcpError(f"runner timed out during {method}")
                self._cv.wait(timeout=remaining)
                if self._proc is not None and self._proc.poll() is not None and self._pending.get(msg_id) is None:
                    raise AcpError(self._failure_text(method))
            message = self._pending.pop(msg_id) or {}
        if "error" in message:
            error = message.get("error")
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise AcpError(detail or f"{method} failed")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def _write(self, payload: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise AcpError("runner is not running")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        with self._write_lock:
            proc.stdin.write(line)
            proc.stdin.flush()

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._progress(line)
                    continue
                if not isinstance(message, dict):
                    continue
                method = message.get("method")
                msg_id = message.get("id")
                if isinstance(method, str) and msg_id is not None and "result" not in message and "error" not in message:
                    self._answer_request(method, msg_id, message.get("params"))
                    continue
                if msg_id is not None and method is None:
                    with self._cv:
                        if msg_id in self._pending:
                            self._pending[msg_id] = message
                        self._cv.notify_all()
                    continue
                if method == "session/update":
                    self._on_update(message.get("params"))
        finally:
            with self._cv:
                self._cv.notify_all()

    def _answer_request(self, method: str, msg_id: object, params: object) -> None:
        del params
        if method == "session/request_permission":
            result: dict = {"outcome": {"outcome": "cancelled"}}
            self._progress("Runner asked to act. Cancelled until you approve it here.")
        else:
            result = {}
            self._progress(f"Ignored runner request {method}.")
        try:
            self._write({"jsonrpc": "2.0", "id": msg_id, "result": result})
        except AcpError:
            return

    def _on_update(self, params: object) -> None:
        if not isinstance(params, dict):
            return
        update = params.get("update")
        if not isinstance(update, dict):
            return
        kind = str(update.get("sessionUpdate") or update.get("session_update") or "")
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            text = _text_of(update.get("content"))
            if text:
                self.turn.text += text
                self._progress(text.strip())
            return
        if kind in {"tool_call", "tool_call_update"}:
            title = str(update.get("title") or update.get("kind") or "tool")
            self._progress(title)
            for path in _paths_of(update):
                if path not in self.turn.paths:
                    self.turn.paths.append(path)

    def _progress(self, text: str) -> None:
        if self._on_progress is None:
            return
        clean = text.strip()
        if clean:
            self._on_progress(clean)

    def _failure_text(self, method: str) -> str:
        proc = self._proc
        detail = ""
        if proc is not None and proc.stderr is not None:
            try:
                detail = proc.stderr.read().strip()
            except Exception:
                detail = ""
        if detail:
            return detail.splitlines()[-1][:400]
        code = proc.returncode if proc is not None else "?"
        return f"runner exited ({code}) during {method}"


def _text_of(content: object) -> str:
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text") or "")
        return str(content.get("text") or "")
    if isinstance(content, list):
        return "".join(_text_of(item) for item in content)
    if isinstance(content, str):
        return content
    return ""


def _paths_of(update: dict) -> list[str]:
    found: list[str] = []
    for key in ("locations", "content"):
        value = update.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    path = item.get("path")
                    if isinstance(path, str) and path.strip():
                        found.append(path.strip())
        elif isinstance(value, dict):
            path = value.get("path")
            if isinstance(path, str) and path.strip():
                found.append(path.strip())
    return found
