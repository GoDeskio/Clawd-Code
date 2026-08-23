"""Tests for the desktop runtime, host API, attachments, and permission gating."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.desktop.attachments import attach_clipboard_text, attach_path, render_attachments
from src.desktop.runtime import DesktopRuntime, provider_limit_hint
from src.desktop.server import DesktopServer
from src.providers.base import ChatResponse
from src.tool_system.permissions import maybe_ask_for_gated_tool
from src.tool_system.tools.bash import BashTool
from src.tool_system.tools.web_fetch import WebFetchTool
from src.tool_system.context import ToolContext
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.protocol import ToolCall
from src.agent.session import Session


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class DesktopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.workspace = Path(self.tmp.name) / "workspace"
        self.workspace.mkdir()
        self.home_patch = patch("src.config.Path.home", return_value=self.home)
        self.session_home = patch("src.agent.session.Path.home", return_value=self.home)
        self.home_patch.start()
        self.session_home.start()

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.session_home.stop()
        self.tmp.cleanup()


class TestGatedPermissions(DesktopTestCase):
    def test_ungated_bash_allows_without_handler(self) -> None:
        ctx = ToolContext(workspace_root=self.workspace)
        result = BashTool().check_permissions({"command": "echo hi"}, ctx)
        self.assertEqual(result.behavior, PermissionBehavior.ALLOW)

    def test_gated_bash_asks(self) -> None:
        ctx = ToolContext(workspace_root=self.workspace, gate_destructive_tools=True)
        result = BashTool().check_permissions({"command": "echo hi"}, ctx)
        self.assertEqual(result.behavior, PermissionBehavior.ASK)

    def test_session_grant_skips_ask(self) -> None:
        ctx = ToolContext(workspace_root=self.workspace, gate_destructive_tools=True)
        ctx.session_grants.add("bash")
        result = maybe_ask_for_gated_tool(ctx, "Bash", "run it")
        self.assertEqual(result.behavior, PermissionBehavior.ALLOW)

    def test_webfetch_asks_when_gated(self) -> None:
        ctx = ToolContext(workspace_root=self.workspace, gate_destructive_tools=True)
        result = WebFetchTool().check_permissions({"url": "https://example.com"}, ctx)
        self.assertEqual(result.behavior, PermissionBehavior.ASK)

    def test_dispatch_denies_gated_write_without_handler(self) -> None:
        from src.tool_system.registry import ToolRegistry
        from src.tool_system.tools.write import FileWriteTool

        ctx = ToolContext(workspace_root=self.workspace, gate_destructive_tools=True)
        registry = ToolRegistry([FileWriteTool()])
        result = registry.dispatch(
            ToolCall(name="Write", input={"file_path": str(self.workspace / "a.py"), "content": "x"}),
            ctx,
        )
        self.assertTrue(result.is_error)
        error_msg = result.output.get("error", "").lower()
        self.assertTrue(
            "permission" in error_msg or "write file" in error_msg,
            f"expected a permission ask/deny, got: {error_msg}",
        )


class TestAttachments(DesktopTestCase):
    def test_attach_text_file(self) -> None:
        path = self.workspace / "note.py"
        path.write_text("print(1)\n", encoding="utf-8")
        item = attach_path(path)
        self.assertFalse(item.omitted)
        self.assertIn("print(1)", item.text)

    def test_clipboard_is_user_provided_only(self) -> None:
        item = attach_clipboard_text("secret-from-user-click")
        self.assertEqual(item.kind, "clipboard")
        self.assertIn("secret-from-user-click", render_attachments([item]))

    def test_empty_clipboard_omitted(self) -> None:
        item = attach_clipboard_text("   ")
        self.assertTrue(item.omitted)


class TestDesktopRuntime(DesktopTestCase):
    def _runtime(self) -> DesktopRuntime:
        runtime = DesktopRuntime(workspace=self.workspace, permission_timeout_s=2.0)
        runtime.provider = MagicMock()
        runtime.provider.model = "test-model"
        runtime.provider.chat_stream_response.side_effect = NotImplementedError()
        runtime.session.model = "test-model"
        return runtime

    def test_setup_required_without_key(self) -> None:
        runtime = DesktopRuntime(workspace=self.workspace)
        self.assertTrue(runtime.needs_setup())
        job_id = runtime.start_chat("hello")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1]))
        events, done = runtime.drain_events(job_id)
        self.assertTrue(done)
        self.assertTrue(any(ev.get("needs_setup") for ev in events))

    def test_login_does_not_echo_raw_key(self) -> None:
        runtime = DesktopRuntime(workspace=self.workspace)
        status = runtime.login("openai", "sk-test-secret-key-123456", default_model="gpt-4o-mini")
        self.assertFalse(status["needs_setup"])
        masked = status["config"]["providers"]["openai"]["api_key_masked"]
        self.assertNotIn("sk-test-secret-key-123456", json.dumps(status))
        self.assertTrue(masked)

    def test_multi_turn_tool_loop_and_permission_allow(self) -> None:
        runtime = self._runtime()
        target = self.workspace / "hello.py"
        runtime.provider.chat.side_effect = [
            ChatResponse(
                content="writing",
                model="test-model",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="tool_use",
                tool_uses=[{
                    "id": "toolu_1",
                    "name": "Write",
                    "input": {"file_path": str(target), "content": "print('hello')"},
                }],
            ),
            ChatResponse(
                content="created",
                model="test-model",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="stop",
            ),
        ]

        def approver() -> None:
            def has_perm() -> bool:
                return bool(runtime.pending_permissions())
            self.assertTrue(_wait_until(has_perm))
            req = runtime.pending_permissions()[0]
            runtime.resolve_permission(req["request_id"], "always")

        thread = threading.Thread(target=approver)
        thread.start()
        job_id = runtime.start_chat("create hello.py")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1], timeout=5))
        thread.join(timeout=2)
        events, done = runtime.drain_events(job_id)
        self.assertTrue(done)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "print('hello')")
        types = [ev.get("type") for ev in events]
        self.assertIn("tool_use", types)
        self.assertIn("done", types)
        self.assertIn("write", runtime.tool_context.session_grants)

    def test_slash_help_is_local(self) -> None:
        runtime = self._runtime()
        job_id = runtime.start_chat("/help")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1]))
        events, _ = runtime.drain_events(job_id)
        done = [ev for ev in events if ev.get("type") == "done"][0]
        self.assertIn("/skills", done["text"])
        runtime.provider.chat.assert_not_called()

    def test_session_list_roundtrip(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("first question about tests")
        summary = runtime.save_session()
        listed = Session.list_sessions()
        self.assertEqual(listed[0]["session_id"], summary["session_id"])
        self.assertIn("first question", listed[0]["title"])

    def test_token_usage_persists_and_resets_on_new_chat(self) -> None:
        runtime = self._runtime()
        runtime.session.record_usage({"input_tokens": 11, "output_tokens": 7})
        saved = runtime.save_session()
        self.assertEqual(saved["token_usage"]["input_tokens"], 11)
        self.assertEqual(saved["token_usage"]["output_tokens"], 7)
        self.assertEqual(saved["token_usage"]["total_tokens"], 18)

        fresh = runtime.new_session()
        self.assertEqual(fresh["token_usage"]["total_tokens"], 0)

        restored = runtime.load_session(saved["session_id"])
        self.assertEqual(restored["token_usage"]["total_tokens"], 18)
        self.assertEqual(runtime.status()["session"]["token_usage"]["total_tokens"], 18)
        dumped = json.dumps(runtime.status())
        self.assertNotIn("out of tokens", dumped.lower())
        self.assertNotIn("buy tokens", dumped.lower())

    def test_provider_limit_is_not_a_hard_stop(self) -> None:
        hint = provider_limit_hint("429 insufficient_quota billing")
        self.assertIn("Switch to Hugging Face", hint)
        self.assertNotIn("Buy", hint)
        self.assertNotIn("upgrade", hint.lower())
        runtime = self._runtime()
        runtime.provider.chat.side_effect = RuntimeError("Error 429 rate_limit exceeded")
        job_id = runtime.start_chat("hello")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1]))
        events, _ = runtime.drain_events(job_id)
        error = [ev for ev in events if ev.get("type") == "error"][0]
        self.assertTrue(error.get("provider_limit"))
        self.assertIn("not a Jonathan Ai token store", error["error"])
        # Chat stays usable — a new turn is accepted, no quota wall.
        runtime.provider.chat.side_effect = None
        runtime.provider.chat.return_value = ChatResponse(
            content="ok",
            model="test-model",
            usage={"input_tokens": 2, "output_tokens": 1},
            finish_reason="stop",
        )
        job2 = runtime.start_chat("try again")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job2)[1]))
        events2, done = runtime.drain_events(job2)
        self.assertTrue(done)
        self.assertTrue(any(ev.get("type") == "done" and ev.get("text") == "ok" for ev in events2))


class TestDesktopServer(DesktopTestCase):
    def test_health_and_chat_api(self) -> None:
        runtime = DesktopRuntime(workspace=self.workspace, permission_timeout_s=2.0)
        runtime.provider = MagicMock()
        runtime.provider.model = "test-model"
        runtime.provider.chat_stream_response.side_effect = NotImplementedError()
        runtime.provider.chat.return_value = ChatResponse(
            content="pong",
            model="test-model",
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="stop",
        )
        runtime.session.model = "test-model"
        server = DesktopServer(runtime, host="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)

        health = json.loads(urllib.request.urlopen(f"{server.url}api/health", timeout=2).read())
        self.assertTrue(health["ok"])

        req = urllib.request.Request(
            f"{server.url}api/chat",
            data=json.dumps({"text": "hello from the ui"}).encode(),
            headers={"Content-Type": "application/json", "X-Clawd-Token": server.token},
            method="POST",
        )
        payload = json.loads(urllib.request.urlopen(req, timeout=2).read())
        job_id = payload["job_id"]
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1]))
        events_req = urllib.request.Request(
            f"{server.url}api/jobs/events?job_id={job_id}",
            headers={"X-Clawd-Token": server.token},
        )
        events = json.loads(urllib.request.urlopen(events_req, timeout=2).read())
        self.assertTrue(events["done"])
        self.assertTrue(any(ev.get("type") == "done" and ev.get("text") == "pong" for ev in events["events"]))
        done = [ev for ev in events["events"] if ev.get("type") == "done"][0]
        self.assertGreaterEqual((done.get("usage") or {}).get("total_tokens") or 0, 1)
        self.assertGreaterEqual(runtime.session.token_usage["total_tokens"], 1)

    def test_api_rejects_missing_token(self) -> None:
        server = DesktopServer(DesktopRuntime(workspace=self.workspace), host="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)
        req = urllib.request.Request(f"{server.url}api/status")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=2)
        self.assertEqual(ctx.exception.code, 401)

    def test_static_ui_is_served(self) -> None:
        server = DesktopServer(DesktopRuntime(workspace=self.workspace), host="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)
        html = urllib.request.urlopen(server.url, timeout=2).read().decode()
        self.assertIn("Jonathan Ai", html)
        self.assertIn("Hugging Face", html)
        self.assertIn("Local LLM", html)
        self.assertIn("GitHub", html)
        self.assertIn("Create repo and push", html)
        self.assertIn("informational", html)
        self.assertIn("app.js", html)


if __name__ == "__main__":
    unittest.main()
