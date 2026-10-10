"""Browser tests. Chrome and the network are mocked."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.browser.actions import REDACT_EXPRESSION, check_browser_permission, sensitive_kind
from src.browser.profile import chrome_launch_command, profile_dir, profile_port
from src.browser.sources import BrowserError, assert_browser_download_url, download_browser
from src.desktop.runtime import _HELP_TEXT
from src.tool_system.context import ToolContext
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.browser import BrowserTool


class FakeTransport:
    def __init__(self, *, title: str = "Example", body: str = "hello") -> None:
        self.calls: list[tuple[str, dict | None]] = []
        self.connected: list[tuple[Path, int]] = []
        self.closed = False
        self.title = title
        self.body = body

    def connect(self, data_dir: Path, port: int) -> None:
        self.connected.append((Path(data_dir), port))

    def send(self, method: str, params: dict | None = None) -> dict:
        self.calls.append((method, params))
        expression = ""
        if params:
            expression = str(params.get("expression") or "")
        if expression == "document.title":
            return {"result": {"value": self.title}}
        if "innerText" in expression:
            return {"result": {"value": self.body}}
        if method == "Page.captureScreenshot":
            return {"data": b"\x89PNG redacted"}
        return {"result": {"value": "ok"}}

    def close(self) -> None:
        self.closed = True


class BrowserTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "profiles"
        self.workspace = Path(self.tmp.name) / "workspace"
        self.workspace.mkdir()
        self.transport = FakeTransport()
        self.ctx = ToolContext(workspace_root=self.workspace)
        self.ctx.browser_transport = self.transport
        self.ctx.browser_profile_root = self.root

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _dispatch(self, payload: dict, *, allow: bool | None = True):
        if allow is None:
            self.ctx.permission_handler = None
        else:
            self.ctx.permission_handler = lambda _name, _message, _suggestion: (allow, False)
        registry = ToolRegistry([BrowserTool()])
        return registry.dispatch(ToolCall(name="Browser", input=payload), self.ctx)


class TestDownloads(BrowserTestCase):
    def test_official_sources_are_allowed(self) -> None:
        for url in (
            "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json",
            "https://storage.googleapis.com/chrome-for-testing-public/131.0.6778.85/linux64/chrome-linux64.zip",
            "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/131.0.6778.85/linux64/chrome-linux64.zip",
            "https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/1148/chromium-linux.zip",
            "https://playwright.azureedge.net/builds/chromium/1148/chromium-linux.zip",
            "https://playwright.download.prss.microsoft.com/dbazure/download/playwright/builds/chromium/1148/chromium-linux.zip",
        ):
            self.assertEqual(assert_browser_download_url(url), url)

    def test_npmmirror_is_refused_before_fetch(self) -> None:
        calls: list[str] = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            return b"nope"

        blocked = (
            "https://cdn.npmmirror.com/binaries/playwright/builds/chromium/1148/chromium-linux.zip",
            "https://registry.npmmirror.com/-/binary/chrome-for-testing/chrome.zip",
            "https://cdn.playwright.dev.npmmirror.com/chromium/chrome.zip",
            "http://cdn.playwright.dev/builds/chromium/1148/chromium-linux.zip",
            "https://storage.googleapis.com/other-bucket/chrome.zip",
            "https://example.com/chrome.zip",
        )
        for url in blocked:
            with self.assertRaises(BrowserError):
                download_browser(url, self.root / "chrome.zip", fetch=fetch)
        self.assertEqual(calls, [])

    def test_sources_do_not_request_npmmirror(self) -> None:
        for path in Path("src/browser").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("https://cdn.npmmirror", text)
            self.assertNotIn("https://registry.npmmirror", text)
            self.assertFalse(any("\u4e00" <= char <= "\u9fff" for char in text), path.name)


class TestApproval(BrowserTestCase):
    def test_ordinary_actions_use_the_gate_and_honor_a_session_grant(self) -> None:
        self.ctx.gate_destructive_tools = True
        asked = check_browser_permission({"action": "navigate", "url": "https://example.com"}, self.ctx)
        self.assertEqual(asked.behavior, PermissionBehavior.ASK)
        self.ctx.session_grants.add("browser")
        allowed = check_browser_permission({"action": "navigate", "url": "https://example.com"}, self.ctx)
        self.assertEqual(allowed.behavior, PermissionBehavior.ALLOW)
        self.ctx.session_grants.add("*")
        still = check_browser_permission({"action": "screenshot"}, self.ctx)
        self.assertEqual(still.behavior, PermissionBehavior.ALLOW)

    def test_submit_purchase_and_login_ignore_session_grants(self) -> None:
        self.ctx.gate_destructive_tools = True
        self.ctx.session_grants.update({"browser", "*"})
        cases = (
            ({"action": "submit", "selector": "form"}, "submit"),
            ({"action": "purchase"}, "purchase"),
            ({"action": "login", "text": "secret"}, "login"),
            ({"action": "click", "text": "Place order"}, "purchase"),
            ({"action": "click", "selector": "button[type=submit]", "text": "Send"}, "submit"),
            ({"action": "fill", "selector": "input[type=password]", "text": "hunter2hunter2"}, "login"),
            ({"action": "click", "text": "Log in"}, "login"),
        )
        for payload, kind in cases:
            self.assertEqual(sensitive_kind(payload), kind, payload)
            result = check_browser_permission(payload, self.ctx)
            self.assertEqual(result.behavior, PermissionBehavior.ASK, payload)
            self.assertIn("Approve", result.message or "")

    def test_dispatch_blocks_submit_until_the_handler_allows_it(self) -> None:
        self.ctx.gate_destructive_tools = True
        self.ctx.session_grants.add("browser")
        denied = self._dispatch({"action": "submit", "selector": "form"}, allow=None)
        self.assertTrue(denied.is_error)
        self.assertIn("Approve", json.dumps(denied.output))
        self.assertEqual(self.transport.connected, [])
        allowed = self._dispatch({"action": "submit", "selector": "form"}, allow=True)
        self.assertFalse(allowed.is_error)
        self.assertEqual(allowed.output["action"], "submit")
        self.assertTrue(self.transport.connected)


class TestSession(BrowserTestCase):
    def test_profile_persists_across_close(self) -> None:
        first = self._dispatch({"action": "navigate", "url": "https://example.com", "profile": "main"})
        data_dir = Path(first.output["profile_dir"])
        cookies = data_dir / "Default" / "Cookies"
        cookies.parent.mkdir(parents=True)
        cookies.write_bytes(b"session-cookie")
        closed = self._dispatch({"action": "close_session", "profile": "main"})
        self.assertTrue(closed.output["persisted"])
        self.assertTrue(self.transport.closed)
        self.assertTrue(cookies.is_file())
        self.assertEqual(cookies.read_bytes(), b"session-cookie")
        again = profile_dir("main", self.root)
        self.assertEqual(again, data_dir)
        self.assertEqual(profile_port(again), profile_port(data_dir))

    def test_users_do_not_share_profiles(self) -> None:
        with patch("src.agent.memory.current_user_id", return_value="ada"):
            ada = profile_dir("main", self.root)
            (ada / "marker").write_text("ada", encoding="utf-8")
        with patch("src.agent.memory.current_user_id", return_value="bob"):
            bob = profile_dir("main", self.root)
        self.assertNotEqual(ada, bob)
        self.assertFalse((bob / "marker").exists())
        self.assertTrue((ada / "marker").is_file())

    def test_launch_uses_the_persistent_profile_on_localhost(self) -> None:
        command = chrome_launch_command("/usr/bin/chromium", Path("/tmp/profile"), 9333)
        rendered = " ".join(command)
        self.assertIn("--user-data-dir=/tmp/profile", rendered)
        self.assertIn("--remote-debugging-port=9333", rendered)
        self.assertIn("--remote-debugging-address=127.0.0.1", rendered)
        self.assertNotIn("npmmirror", rendered)

    def test_rejects_a_profile_path_escape(self) -> None:
        with self.assertRaises(BrowserError):
            profile_dir("../etc", self.root)


class TestActions(BrowserTestCase):
    def test_navigate_masks_secrets_and_does_not_download(self) -> None:
        secret = "password=supersecretvalue"
        self.transport.body = f"welcome {secret}"
        calls: list[str] = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            return b""

        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            result = self._dispatch({"action": "navigate", "url": f"https://example.com/?{secret}"})
        self.assertFalse(result.is_error)
        blob = json.dumps(result.output)
        self.assertNotIn("supersecretvalue", blob)
        self.assertIn("example.com", blob)
        self.assertEqual(calls, [])
        self.assertEqual(self.transport.calls[0][0], "Page.navigate")

    def test_screenshot_redacts_before_capture(self) -> None:
        result = self._dispatch({"action": "screenshot", "profile": "main"})
        methods = [method for method, _params in self.transport.calls]
        self.assertEqual(methods[0], "Runtime.evaluate")
        self.assertEqual(self.transport.calls[0][1]["expression"], REDACT_EXPRESSION)
        self.assertEqual(methods[1], "Page.captureScreenshot")
        self.assertTrue(result.output["redacted"])
        self.assertTrue(Path(result.output["screenshot_path"]).is_file())

    def test_typed_secret_is_not_echoed(self) -> None:
        secret = "hunter2hunter2"
        self.ctx.gate_destructive_tools = True
        result = self._dispatch(
            {"action": "fill", "selector": "input[type=password]", "text": secret},
            allow=True,
        )
        self.assertFalse(result.is_error)
        self.assertNotIn(secret, json.dumps(result.output))
        sent = self.transport.calls[-1][1]
        self.assertEqual(sent["text"], secret)

    def test_import_does_not_load_the_websocket_extra(self) -> None:
        import src.browser.cdp as cdp

        self.assertFalse(hasattr(cdp, "websocket"))
        self.assertIn("Browser", _HELP_TEXT)
        self.assertIn("approval", _HELP_TEXT)


if __name__ == "__main__":
    unittest.main()
