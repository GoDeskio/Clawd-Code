"""Localhost HTTP + SSE host for the desktop UI.

Bound to 127.0.0.1 only. API writes require a session token so a page on
another origin cannot drive the agent. Keys never leave ~/.clawd/config.json.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .runtime import DesktopRuntime

WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _json_bytes(payload: Any, status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


class DesktopServer:
    def __init__(
        self,
        runtime: DesktopRuntime | None = None,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token: str | None = None,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("desktop host must be localhost")
        self.runtime = runtime or DesktopRuntime()
        self.host = host
        self.port = int(port)
        self.token = token or os.environ.get("CLAWD_DESKTOP_TOKEN") or secrets.token_urlsafe(24)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def handle_api(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any] | None) -> tuple[int, Any]:
        runtime = self.runtime
        body = body or {}

        if path == "/api/health":
            return 200, {"ok": True, "url": self.url}

        if path == "/api/status" and method == "GET":
            return 200, runtime.status()
        if path == "/api/providers" and method == "GET":
            return 200, runtime.provider_catalog()
        if path == "/api/config" and method == "GET":
            return 200, runtime.status()["config"]
        if path == "/api/login" and method == "POST":
            return 200, runtime.login(
                str(body.get("provider") or ""),
                str(body.get("api_key") or ""),
                base_url=body.get("base_url"),
                default_model=body.get("default_model"),
            )
        if path == "/api/provider" and method == "POST":
            return 200, runtime.set_provider(str(body.get("provider") or ""), model=body.get("model"))
        if path == "/api/workspace" and method == "POST":
            return 200, runtime.set_workspace(str(body.get("path") or ""))
        if path == "/api/sessions" and method == "GET":
            return 200, {"sessions": runtime.list_sessions(), "current": runtime.session.to_summary()}
        if path == "/api/sessions" and method == "POST":
            return 200, runtime.new_session()
        if path == "/api/sessions/save" and method == "POST":
            return 200, runtime.save_session()
        if path == "/api/sessions/load" and method == "POST":
            return 200, runtime.load_session(str(body.get("session_id") or ""))
        if path == "/api/skills" and method == "GET":
            return 200, {"skills": runtime.list_skills()}
        if path == "/api/commands" and method == "GET":
            return 200, {"commands": runtime.list_commands()}
        if path == "/api/tools" and method == "GET":
            return 200, {"tools": runtime.list_tools()}
        if path == "/api/attachments" and method == "POST":
            return 200, {"attachments": runtime.attach_files(body.get("attachments") or body.get("files"))}
        if path == "/api/chat" and method == "POST":
            job_id = runtime.start_chat(str(body.get("text") or ""), attachments=body.get("attachments"))
            return 200, {"job_id": job_id}
        if path == "/api/jobs/events" and method == "GET":
            job_id = (query.get("job_id") or [""])[0]
            after = int((query.get("after") or ["0"])[0] or 0)
            events, done = runtime.drain_events(job_id, after=after)
            return 200, {"events": events, "done": done, "after": after + len(events)}
        if path.startswith("/api/jobs/") and path.endswith("/cancel") and method == "POST":
            job_id = path.split("/")[3]
            runtime.cancel_job(job_id)
            return 200, {"cancelled": True, "job_id": job_id}
        if path == "/api/permissions" and method == "GET":
            return 200, {"pending": runtime.pending_permissions()}
        if path == "/api/permissions" and method == "POST":
            return 200, runtime.resolve_permission(str(body.get("request_id") or ""), str(body.get("decision") or ""))
        return 404, {"error": f"unknown route: {method} {path}"}

    def serve_forever(self) -> None:
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.serve_forever()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        # If port was 0, capture the ephemeral port.
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="clawd-desktop-http")
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def wait_ready(self, timeout_s: float = 5.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._httpd is not None:
                return True
            time.sleep(0.02)
        return self._httpd is not None

    def _authorized(self, headers) -> bool:
        provided = headers.get("X-Clawd-Token") or headers.get("x-clawd-token")
        if provided == self.token:
            return True
        cookie = headers.get("Cookie") or ""
        return f"clawd_token={self.token}" in cookie

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                return

            def _send(self, status: int, body: bytes, content_type: str, extra: list[tuple[str, str]] | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for key, value in extra or []:
                    self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object")
                return data

            def do_OPTIONS(self) -> None:  # noqa: N802
                self._send(204, b"", "text/plain", [("Allow", "GET,POST,OPTIONS,HEAD")])

            def do_HEAD(self) -> None:  # noqa: N802
                self._dispatch("HEAD")

            def do_GET(self) -> None:  # noqa: N802
                self._dispatch("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch("POST")

            def _dispatch(self, method: str) -> None:
                parsed = urlparse(self.path)
                path = parsed.path or "/"
                query = parse_qs(parsed.query)

                if path == "/api/events":
                    self._sse(query)
                    return

                if path.startswith("/api/"):
                    if path != "/api/health" and not server._authorized(self.headers):
                        status, body, ctype = _json_bytes({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        self._send(status, body, ctype)
                        return
                    try:
                        payload = self._read_json() if method == "POST" else {}
                        status, result = server.handle_api(method, path, query, payload)
                    except ValueError as exc:
                        status, body, ctype = _json_bytes({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                        self._send(status, body, ctype)
                        return
                    except Exception as exc:
                        status, body, ctype = _json_bytes({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                        self._send(status, body, ctype)
                        return
                    extra = []
                    if path == "/api/health":
                        extra.append(("Set-Cookie", f"clawd_token={server.token}; Path=/; HttpOnly; SameSite=Lax"))
                    status, body, ctype = _json_bytes(result, status)
                    self._send(status, body, ctype, extra)
                    return

                self._static(path)

            def _sse(self, query: dict[str, list[str]]) -> None:
                if not server._authorized(self.headers):
                    status, body, ctype = _json_bytes({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    self._send(status, body, ctype)
                    return
                job_id = (query.get("job_id") or [""])[0]
                after = int((query.get("after") or ["0"])[0] or 0)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while True:
                        events, done = server.runtime.wait_events(job_id, after=after, timeout=15.0)
                        for event in events:
                            payload = json.dumps(event, ensure_ascii=False)
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                            after += 1
                        if done:
                            self.wfile.write(b"data: {\"type\":\"stream_end\"}\n\n")
                            self.wfile.flush()
                            break
                except BrokenPipeError:
                    return

            def _static(self, path: str) -> None:
                relative = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
                target = (WEB_DIR / relative).resolve()
                if WEB_DIR not in target.parents and target != WEB_DIR:
                    self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                    return
                if not target.exists() or not target.is_file():
                    fallback = WEB_DIR / "index.html"
                    target = fallback
                data = target.read_bytes()
                ctype = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".json": "application/json",
                    ".png": "image/png",
                }.get(target.suffix, "application/octet-stream")
                extra = []
                if target.name == "index.html":
                    extra.append(("Set-Cookie", f"clawd_token={server.token}; Path=/; HttpOnly; SameSite=Lax"))
                self._send(200, data, ctype, extra)

        return Handler


def create_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    workspace: str | None = None,
    token: str | None = None,
) -> DesktopServer:
    runtime = DesktopRuntime(workspace=workspace)
    return DesktopServer(runtime, host=host, port=port, token=token)


def run_desktop(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    workspace: str | None = None,
    open_browser: bool = True,
    token: str | None = None,
) -> int:
    server = create_server(host=host, port=port, workspace=workspace, token=token)
    print(f"Clawd desktop host: {server.url}")
    print("Bound to localhost only. API keys stay in ~/.clawd/config.json.")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping desktop host.")
    finally:
        server.stop()
    return 0
