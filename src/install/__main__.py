"""CLI / UI entry for the first-run install wizard."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .constants import CANONICAL_HTTPS
from .source import default_source_dir
from .wizard import InstallWizard


def _print_progress(event: dict) -> None:
    kind = event.get("type")
    if kind == "step":
        print(f"• {event.get('message')}", flush=True)
    elif kind == "error":
        print(f"ERROR: {event.get('error')}", flush=True)
    elif kind == "done":
        print(f"Installed at {event.get('source_dir')}", flush=True)


def run_cli(args: argparse.Namespace) -> int:
    wizard = InstallWizard()
    print(f"Jonathan Ai install wizard  ·  source {CANONICAL_HTTPS}", flush=True)
    print(f"Install folder: {args.source_dir}", flush=True)
    try:
        result = wizard.run_sync(
            source_dir=args.source_dir,
            from_local=args.from_local,
            skip_desktop_deps=args.skip_desktop_deps,
            clone=args.clone,
            progress=_print_progress,
        )
    except Exception as exc:
        print(f"Install failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: result.get(k) for k in ("source_dir", "venv_python", "commit", "desktop_deps")}, indent=2))
    source = Path(result.get("source_dir") or args.source_dir)
    try:
        from .launch import launch_jonathan_ai
        from .windows_shortcuts import create_windows_shortcuts, find_app_executable

        bundled = Path(__file__).resolve().parents[2] / "packaging" / "windows" / "bin" / "JonathanAi.exe"
        dest_exe = source / "JonathanAi.exe"
        if bundled.exists() and not dest_exe.exists():
            import shutil

            shutil.copy2(bundled, dest_exe)
        icon = source / "src" / "desktop" / "web" / "robot.png"
        create_windows_shortcuts(find_app_executable(source), icon if icon.exists() else None)
    except Exception:
        pass
    if args.launch:
        from .launch import launch_jonathan_ai

        launch_jonathan_ai(source)
        return 0
    print("Start the desktop app with:")
    print(f"  {result.get('venv_python')} -m src.cli desktop")
    print(f"  {result.get('launchers', {}).get('unix') or result.get('source_dir')}/start-desktop.sh")
    return 0


def run_ui(args: argparse.Namespace) -> int:
    wizard = InstallWizard()
    token = args.token or os.environ.get("CLAWD_INSTALL_TOKEN") or "local-install"
    host = "127.0.0.1"
    port = int(args.port)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *a) -> None:  # noqa: A003
            return

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                html = (Path(__file__).parent / "web" / "index.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
                return
            if path == "/api/defaults":
                self._send(200, json.dumps(wizard.defaults()).encode(), "application/json")
                return
            if path == "/api/connectors/github/repos":
                try:
                    from src.connectors.github import GitHubConnector

                    self._send(200, json.dumps({"repos": GitHubConnector().list_repos()}).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/gitlab/projects":
                try:
                    from src.connectors.gitlab import GitLabConnector

                    self._send(200, json.dumps({"projects": GitLabConnector().list_projects()}).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path.startswith("/api/jobs/"):
                job_id = path.split("/")[3]
                after = int((parse_qs(urlparse(self.path).query).get("after") or ["0"])[0] or 0)
                try:
                    events, done, result, error = wizard.drain(job_id, after=after)
                except ValueError as exc:
                    self._send(404, json.dumps({"error": str(exc)}).encode(), "application/json")
                    return
                self._send(200, json.dumps({"events": events, "done": done, "result": result, "error": error}).encode(), "application/json")
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
            if path == "/api/start":
                job_id = wizard.start(
                    source_dir=body.get("source_dir") or args.source_dir,
                    from_local=body.get("from_local") or args.from_local,
                    skip_desktop_deps=bool(body.get("skip_desktop_deps") or args.skip_desktop_deps),
                    clone=bool(body.get("clone") or args.clone),
                )
                self._send(200, json.dumps({"job_id": job_id}).encode(), "application/json")
                return
            if path == "/api/connectors/hf/test":
                from src.providers.huggingface_connect import verify_huggingface_token

                try:
                    result = verify_huggingface_token(str(body.get("api_key") or body.get("token") or ""))
                    self._send(200, json.dumps(result).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/local/scan":
                from src.providers.local_endpoints import scan_local_endpoints

                result = {"endpoints": scan_local_endpoints()}
                self._send(200, json.dumps(result).encode(), "application/json")
                return
            if path == "/api/connect":
                try:
                    from src.providers.connect_flow import save_provider_connection

                    provider = str(body.get("provider") or "")
                    save_provider_connection(
                        provider,
                        api_key=str(body.get("api_key") or ""),
                        base_url=body.get("base_url"),
                        default_model=body.get("default_model") or None,
                    )
                    self._send(200, json.dumps({"ok": True, "provider": provider}).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/github/login":
                try:
                    from src.connectors.github import GitHubConnector

                    result = GitHubConnector().login_with_token(str(body.get("token") or ""), owner=body.get("owner"))
                    self._send(200, json.dumps(result).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/gitlab/login":
                try:
                    from src.connectors.gitlab import GitLabConnector

                    result = GitLabConnector(host=body.get("host")).login_with_token(
                        str(body.get("token") or ""),
                        owner=body.get("owner"),
                        host=body.get("host"),
                    )
                    self._send(200, json.dumps(result).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/mcp":
                try:
                    from src.connectors.store import save_mcp_server

                    result = save_mcp_server(
                        name=str(body.get("name") or ""),
                        command=str(body.get("command") or ""),
                        args=list(body.get("args") or []),
                        url=str(body.get("url") or ""),
                        token=str(body.get("token") or ""),
                    )
                    self._send(200, json.dumps({"ok": True, **result}).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/mcp/test":
                try:
                    from src.connectors.mcp_client import test_mcp_record

                    result = test_mcp_record(body)
                    self._send(200, json.dumps(result).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/agents":
                try:
                    from src.connectors.store import save_agent

                    result = save_agent(
                        name=str(body.get("name") or ""),
                        base_url=str(body.get("base_url") or body.get("url") or ""),
                        api_key=str(body.get("api_key") or body.get("token") or ""),
                    )
                    self._send(200, json.dumps({"ok": True, **result}).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            if path == "/api/connectors/agents/test":
                try:
                    from src.connectors.agents import list_agent_tools, test_agent_endpoint

                    url = str(body.get("base_url") or "")
                    key = str(body.get("api_key") or "")
                    result = test_agent_endpoint(url, key)
                    result["tools"] = list_agent_tools(url, key)
                    self._send(200, json.dumps(result).encode(), "application/json")
                except Exception as exc:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            self._send(404, b"not found", "text/plain")

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Install wizard: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Jonathan Ai from GoDeskio/Clawd-Code")
    parser.add_argument("--source-dir", default=str(default_source_dir()), help="Local source folder (default: ~/Jonathan/Jonathan-Ai)")
    parser.add_argument("--from-local", default=None, help="Copy this existing checkout instead of cloning")
    parser.add_argument("--clone", action="store_true", help="Always clone from GitHub (GoDeskio/Clawd-Code only)")
    parser.add_argument("--skip-desktop-deps", action="store_true", help="Skip npm install for Electron")
    parser.add_argument("--cli", action="store_true", help="Run the wizard in the terminal")
    parser.add_argument("--yes", action="store_true", help="Unattended CLI install (same as --cli)")
    parser.add_argument("--ui", action="store_true", help="Open the graphical wizard")
    parser.add_argument("--gui", action="store_true", help="Open the Windows Next/Install/Finish wizard")
    parser.add_argument("--port", default=8766, help="Wizard UI port")
    parser.add_argument("--token", default=None)
    parser.add_argument("--launch", action="store_true", help="Start the desktop host after install")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.gui or (sys.platform.startswith("win") and not (args.cli or args.yes or args.ui)):
        from .win_gui import run_windows_wizard

        return run_windows_wizard(source_dir=args.source_dir, from_local=args.from_local)
    if args.ui and not (args.cli or args.yes):
        return run_ui(args)
    if args.cli or args.yes or args.launch or not sys.stdin.isatty():
        return run_cli(args)
    return run_ui(args)


if __name__ == "__main__":
    sys.exit(main())
