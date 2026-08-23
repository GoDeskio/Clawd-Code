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
        self.hooks_home = patch("src.connectors.hooks.Path.home", return_value=self.home)
        self.memory_home = patch("src.agent.memory.Path.home", return_value=self.home)
        self.home_patch.start()
        self.session_home.start()
        self.hooks_home.start()
        self.memory_home.start()

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.session_home.stop()
        self.hooks_home.stop()
        self.memory_home.stop()
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
        self.assertIn("/new", done["text"])
        runtime.provider.chat.assert_not_called()

    def test_slash_new_creates_empty_session(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("keep this thread")
        previous = runtime.save_session()
        job_id = runtime.start_chat("/new")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1]))
        events, _ = runtime.drain_events(job_id)
        done = [ev for ev in events if ev.get("type") == "done"][0]
        self.assertEqual(done.get("messages"), [])
        self.assertNotEqual(done["session"]["session_id"], previous["session_id"])
        self.assertEqual(runtime.session.session_id, done["session"]["session_id"])
        self.assertEqual(len(runtime.session.conversation.messages), 0)
        self.assertEqual(runtime.session.token_usage["total_tokens"], 0)
        listed_ids = {item["session_id"] for item in Session.list_sessions()}
        self.assertIn(previous["session_id"], listed_ids)
        runtime.provider.chat.assert_not_called()

    def test_slash_clear_persists_empty_same_session(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("wipe me")
        runtime.session.record_usage({"input_tokens": 4, "output_tokens": 2})
        saved = runtime.save_session()
        job_id = runtime.start_chat("/clear")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1]))
        events, _ = runtime.drain_events(job_id)
        done = [ev for ev in events if ev.get("type") == "done"][0]
        self.assertEqual(done.get("messages"), [])
        self.assertEqual(done["session"]["session_id"], saved["session_id"])
        self.assertEqual(len(runtime.session.conversation.messages), 0)
        self.assertEqual(runtime.session.token_usage["total_tokens"], 0)
        loaded = Session.load(saved["session_id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.conversation.messages), 0)
        runtime.provider.chat.assert_not_called()

    def test_session_list_roundtrip(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("first question about tests")
        summary = runtime.save_session()
        listed = Session.list_sessions()
        self.assertEqual(listed[0]["session_id"], summary["session_id"])
        self.assertIn("first question", listed[0]["title"])

    def test_rename_session_persists(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("this would have been the auto title")
        runtime.save_session()
        renamed = runtime.rename_session(runtime.session.session_id, "My project notes")
        self.assertEqual(renamed["title"], "My project notes")
        self.assertTrue(renamed["custom_title"])
        loaded = Session.load(runtime.session.session_id)
        self.assertEqual(loaded.title, "My project notes")
        self.assertTrue(loaded.custom_title)
        self.assertEqual(Session.list_sessions()[0]["title"], "My project notes")
        runtime.session.conversation.add_user_message("later message should not overwrite title")
        runtime.save_session()
        self.assertEqual(runtime.session.display_title(), "My project notes")

    def test_standalone_chat_omits_other_agents_and_sends_typed_schemas(self) -> None:
        runtime = self._runtime()
        runtime.provider.chat.return_value = ChatResponse(
            content="hello from standalone jonathan",
            model="test-model",
            usage={"input_tokens": 3, "output_tokens": 2},
            finish_reason="stop",
        )
        job_id = runtime.start_chat("hi, no other agent is connected")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_id)[1]))
        events, done = runtime.drain_events(job_id)
        self.assertTrue(done)
        self.assertTrue(any(ev.get("type") == "done" for ev in events))
        self.assertFalse(any(ev.get("needs_setup") for ev in events))
        self.assertTrue(runtime.provider.chat.called)
        kwargs = runtime.provider.chat.call_args.kwargs
        tools = kwargs.get("tools") or []
        names = [tool["name"] for tool in tools]
        self.assertNotIn("ExternalAgent", names)
        self.assertNotIn("MCP", names)
        self.assertNotIn("ListMcpResources", names)
        self.assertNotIn("ReadMcpResource", names)
        self.assertIn("Skill", names)
        for tool in tools:
            self.assertEqual(tool["input_schema"].get("type"), "object", tool["name"])
        self.assertEqual(runtime.status()["version"], "0.2.5")
        self.assertTrue(runtime.status()["standalone"])

    def test_multi_agent_workers_do_not_need_other_products(self) -> None:
        runtime = self._runtime()
        runtime.provider.chat.return_value = ChatResponse(
            content="worker note",
            model="test-model",
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="stop",
        )
        job = runtime.start_multi_agent("Research the mascot then summarize it")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1]))
        events, done = runtime.drain_events(job)
        self.assertTrue(done)
        self.assertTrue(any(ev.get("type") == "workers_started" for ev in events))
        self.assertTrue(any(ev.get("type") == "worker" for ev in events))
        self.assertTrue(any(ev.get("type") == "done" for ev in events))
        for call in runtime.provider.chat.call_args_list:
            self.assertFalse(call.kwargs.get("tools"))

    def test_new_chat_is_empty_and_keeps_previous(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("old thread stays")
        previous = runtime.save_session()
        first = runtime.new_session()
        self.assertNotEqual(first["session_id"], previous["session_id"])
        self.assertEqual(first["message_count"], 0)
        self.assertEqual(first["token_usage"]["total_tokens"], 0)
        self.assertEqual(len(runtime.session.conversation.messages), 0)
        listed_ids = {item["session_id"] for item in Session.list_sessions()}
        self.assertIn(previous["session_id"], listed_ids)
        self.assertIn(first["session_id"], listed_ids)
        second = runtime.new_session()
        self.assertNotEqual(second["session_id"], first["session_id"])
        self.assertEqual(second["message_count"], 0)

    def test_restart_restores_persisted_chats(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("keep this after restart")
        saved = runtime.save_session()
        again = DesktopRuntime(workspace=self.workspace, permission_timeout_s=2.0)
        self.assertEqual(again.session.session_id, saved["session_id"])
        texts = [msg.content for msg in again.session.conversation.messages if isinstance(msg.content, str)]
        self.assertIn("keep this after restart", texts)
        self.assertGreaterEqual(len(Session.list_sessions()), 1)

    def test_memory_from_chat_a_is_visible_in_chat_b(self) -> None:
        runtime = self._runtime()
        runtime.provider.chat.return_value = ChatResponse(
            content="I will remember that.",
            model="test-model",
            usage={"input_tokens": 2, "output_tokens": 2},
            finish_reason="stop",
        )
        job = runtime.start_chat("Remember that the mascot is a robot sketch.")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1]))
        chat_a = runtime.session.session_id
        runtime.new_session()
        self.assertNotEqual(runtime.session.session_id, chat_a)
        job_b = runtime.start_chat("What mascot did we pick?")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job_b)[1]))
        args = runtime.provider.chat.call_args.args
        messages = args[0] if args else runtime.provider.chat.call_args.kwargs.get("messages")
        blob = json.dumps(messages)
        self.assertIn("robot sketch", blob.lower())

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
        self.assertIn("robot.png", html)
        self.assertIn("Conversations", html)
        self.assertIn("0.2.5", html)
        self.assertIn("session-menu", html)
        self.assertIn("app.js", html)

    def test_new_chat_api_is_empty_and_messages_roundtrip(self) -> None:
        runtime = DesktopRuntime(workspace=self.workspace, permission_timeout_s=2.0)
        runtime.provider = MagicMock()
        runtime.provider.model = "test-model"
        runtime.provider.chat_stream_response.side_effect = NotImplementedError()
        runtime.provider.chat.return_value = ChatResponse(
            content="saved reply",
            model="test-model",
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="stop",
        )
        runtime.session.model = "test-model"
        server = DesktopServer(runtime, host="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)
        headers = {"Content-Type": "application/json", "X-Clawd-Token": server.token}

        chat_req = urllib.request.Request(
            f"{server.url}api/chat",
            data=json.dumps({"text": "keep this thread"}).encode(),
            headers=headers,
            method="POST",
        )
        chat = json.loads(urllib.request.urlopen(chat_req, timeout=2).read())
        self.assertTrue(_wait_until(lambda: runtime.drain_events(chat["job_id"])[1]))
        previous_id = runtime.session.session_id

        new_req = urllib.request.Request(
            f"{server.url}api/sessions",
            data=b"{}",
            headers=headers,
            method="POST",
        )
        created = json.loads(urllib.request.urlopen(new_req, timeout=2).read())
        self.assertNotEqual(created["session_id"], previous_id)
        self.assertEqual(created["messages"], [])
        self.assertEqual(created["message_count"], 0)
        self.assertEqual(created["token_usage"]["total_tokens"], 0)

        listed = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"{server.url}api/sessions", headers={"X-Clawd-Token": server.token}),
            timeout=2,
        ).read())
        ids = {item["session_id"] for item in listed["sessions"]}
        self.assertIn(previous_id, ids)
        self.assertIn(created["session_id"], ids)

        messages = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"{server.url}api/sessions/messages", headers={"X-Clawd-Token": server.token}),
            timeout=2,
        ).read())
        self.assertEqual(messages["messages"], [])

        load_req = urllib.request.Request(
            f"{server.url}api/sessions/load",
            data=json.dumps({"session_id": previous_id}).encode(),
            headers=headers,
            method="POST",
        )
        loaded = json.loads(urllib.request.urlopen(load_req, timeout=2).read())
        texts = [msg.get("content") for msg in loaded["messages"]]
        self.assertTrue(any("keep this thread" in str(text) for text in texts))

    def test_rename_api(self) -> None:
        runtime = DesktopRuntime(workspace=self.workspace, permission_timeout_s=2.0)
        runtime.provider = MagicMock()
        runtime.provider.model = "test-model"
        runtime.session.model = "test-model"
        runtime.save_session()
        server = DesktopServer(runtime, host="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)
        req = urllib.request.Request(
            f"{server.url}api/sessions/rename",
            data=json.dumps({"session_id": runtime.session.session_id, "title": "Renamed from API"}).encode(),
            headers={"Content-Type": "application/json", "X-Clawd-Token": server.token},
            method="POST",
        )
        payload = json.loads(urllib.request.urlopen(req, timeout=2).read())
        self.assertEqual(payload["title"], "Renamed from API")
        self.assertTrue(payload["custom_title"])


if __name__ == "__main__":
    unittest.main()
