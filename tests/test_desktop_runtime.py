"""Tests for the desktop runtime, host API, attachments, and permission gating."""

from __future__ import annotations

import json
import base64
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.desktop.attachments import attach_clipboard_text, attach_path, image_source, render_attachments
from src.desktop.runtime import DesktopRuntime, direct_image_request, local_chat_route, provider_limit_hint
from src.desktop.server import DesktopServer
from src.providers.base import ChatResponse
from src.tool_system.permissions import maybe_ask_for_gated_tool
from src.tool_system.tools.bash import BashTool
from src.tool_system.tools.web_fetch import WebFetchTool
from src.tool_system.context import ToolContext
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.protocol import ToolCall
from src.tool_system.agent_loop import AgentLoopResult
from src.tool_system.tools.terminal import TerminalTool, discover_terminals
from src.tool_system.tools.device_control import DeviceControlTool
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

    def test_device_control_uses_master_grant(self) -> None:
        ctx = ToolContext(workspace_root=self.workspace, gate_destructive_tools=True)
        tool = DeviceControlTool()
        self.assertEqual(tool.check_permissions({"action": "inventory"}, ctx).behavior, PermissionBehavior.ASK)
        ctx.session_grants.add("*")
        self.assertEqual(tool.check_permissions({"action": "inventory"}, ctx).behavior, PermissionBehavior.ALLOW)
        with patch("src.tool_system.tools.device_control.discover_device_controls", return_value={"counts": {"applications": 1}}):
            result = tool.run({"action": "inventory"}, ctx)
        self.assertFalse(result.is_error)
        self.assertEqual(result.output["counts"]["applications"], 1)

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

    def test_image_attachment_keeps_pixels_for_model_context(self) -> None:
        from PIL import Image

        path = self.workspace / "photo.png"
        Image.new("RGB", (24, 16), "purple").save(path)
        item = attach_path(path)
        self.assertTrue(item.is_image)
        self.assertFalse(item.omitted)
        source = image_source(item)
        self.assertEqual(source["type"], "base64")
        self.assertEqual(source["media_type"], "image/png")
        self.assertTrue(source["data"])

    def test_inline_binary_upload_remains_an_image_instead_of_garbled_text(self) -> None:
        from PIL import Image
        import io

        buffer = io.BytesIO()
        Image.new("RGB", (18, 12), "teal").save(buffer, format="JPEG")
        runtime = DesktopRuntime(workspace=self.workspace)
        rows = runtime.attach_files([{
            "kind": "file",
            "name": "dropped-photo.jpg",
            "media_type": "image/jpeg",
            "data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }], runtime.session.session_id)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_image"])
        self.assertFalse(rows[0]["omitted"])
        self.assertTrue(Path(rows[0]["path"]).is_file())
        self.assertIn("/api/attachments/view", rows[0]["preview_url"])
        self.assertIn("/api/attachments/download", rows[0]["download_url"])


class TestDesktopRuntime(DesktopTestCase):
    def _runtime(self) -> DesktopRuntime:
        runtime = DesktopRuntime(workspace=self.workspace, permission_timeout_s=2.0)
        runtime.provider = MagicMock()
        runtime.provider.model = "test-model"
        runtime.provider.chat_stream_response.side_effect = NotImplementedError()
        runtime.session.model = "test-model"
        return runtime

    def test_setup_required_without_key(self) -> None:
        with patch("src.desktop.runtime.discover_local_environment", return_value={
            "runtimes": [], "endpoints": [], "selected": None, "auto_started": False,
        }):
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

    def test_full_device_access_requires_exact_confirmation_and_is_revocable(self) -> None:
        runtime = self._runtime()
        with self.assertRaisesRegex(ValueError, "ENABLE FULL ACCESS"):
            runtime.configure_device_access(enabled=True, confirmation="yes")
        with patch("src.desktop.runtime.record_action"):
            enabled = runtime.configure_device_access(enabled=True, confirmation="ENABLE FULL ACCESS")
        self.assertTrue(enabled["enabled"])
        self.assertTrue(runtime.tool_context.permission_context.full_system_access)
        self.assertIn("*", runtime.tool_context.session_grants)
        outside = Path(self.tmp.name) / "outside.txt"
        self.assertEqual(runtime.tool_context.ensure_allowed_path(outside), outside.resolve())
        with patch("src.desktop.runtime.record_action"):
            disabled = runtime.configure_device_access(enabled=False)
        self.assertFalse(disabled["enabled"])
        self.assertFalse(runtime.tool_context.permission_context.full_system_access)
        self.assertNotIn("*", runtime.tool_context.session_grants)

    def test_device_access_api_is_exposed_in_status(self) -> None:
        runtime = self._runtime()
        status = runtime.status()["device_access"]
        self.assertFalse(status["enabled"])
        self.assertIn("launch installed applications and browsers", status["capabilities"])

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

    def test_uploaded_image_is_staged_and_added_as_multimodal_context(self) -> None:
        from PIL import Image

        runtime = self._runtime()
        source = Path(self.tmp.name) / "outside.png"
        Image.new("RGB", (32, 20), "orange").save(source)
        staged = runtime.attach_files([{"kind": "file", "path": str(source)}], runtime.session.session_id)
        self.assertEqual(len(staged), 1)
        self.assertTrue(staged[0]["is_image"])
        self.assertIn("/api/attachments/view", staged[0]["preview_url"])
        self.assertIn("/api/attachments/download", staged[0]["download_url"])
        staged_path = Path(staged[0]["path"])
        self.assertTrue(staged_path.is_file())
        self.assertIn(runtime.session.session_id, str(staged_path))
        captured = {}

        def fake_loop(*, conversation, **_kwargs):
            captured["messages"] = conversation.get_messages()
            conversation.add_assistant_message("I can see the orange image.")
            return AgentLoopResult(response_text="I can see the orange image.", usage={}, num_turns=1)

        with patch("src.desktop.runtime.run_agent_loop", side_effect=fake_loop):
            job = runtime.start_chat("What color is this?", attachments=staged)
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1], timeout=5))
        content = captured["messages"][-1]["content"]
        self.assertTrue(any(block.get("type") == "image" and block.get("source", {}).get("data") for block in content))
        self.assertIn(str(staged_path), content[0]["text"])
        transcript = runtime.session.export_messages()
        rich_user = next(row for row in transcript if row["role"] == "user" and isinstance(row["content"], list))
        exported_image = next(block for block in rich_user["content"] if block.get("type") == "image")
        self.assertEqual(exported_image["name"], "outside.png")
        self.assertTrue(exported_image["source"]["data"])
        exported_text = next(block["text"] for block in rich_user["content"] if block.get("type") == "text")
        self.assertEqual(exported_text, "What color is this?")
        self.assertNotIn(str(staged_path), exported_text)

    def test_explicit_image_prompt_runs_local_engine_without_chat_provider(self) -> None:
        runtime = DesktopRuntime(workspace=self.workspace)
        runtime.provider = None
        artifact = {
            "name": "generated.png", "id": "generated.png", "size": 123,
            "is_image": True, "media_type": "image/png",
            "view_url": "/api/artifacts/view?name=generated.png",
            "download_url": "/api/artifacts/download?name=generated.png",
        }
        from src.tool_system.protocol import ToolResult

        with patch("src.desktop.runtime.ImageStudioTool.run", return_value=ToolResult(
            name="ImageStudio", output={"action": "generate", "artifact": artifact, "artifacts": [artifact]},
        )) as run_image:
            job = runtime.start_chat("/image a friendly blue robot in a workshop")
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1], timeout=5))
        events, done = runtime.drain_events(job)
        self.assertTrue(done)
        self.assertEqual([event["type"] for event in events], ["job_started", "user", "tool_use", "tool_result", "done"])
        tool_input = run_image.call_args.args[0]
        self.assertEqual(tool_input["engine"], "local")
        self.assertEqual((tool_input["width"], tool_input["height"]), (512, 512))
        self.assertIn("friendly blue robot", tool_input["prompt"])
        transcript = runtime.session.export_messages()
        self.assertTrue(any(row["role"] == "assistant" and isinstance(row["content"], list) for row in transcript))
        self.assertIn("ready to download", transcript[1]["content"].lower())

    def test_uploaded_image_edit_prompt_uses_exact_staged_source(self) -> None:
        from PIL import Image
        from src.tool_system.protocol import ToolResult

        runtime = self._runtime()
        source = Path(self.tmp.name) / "source.png"
        Image.new("RGB", (20, 20), "red").save(source)
        staged = runtime.attach_files([{"kind": "file", "path": str(source)}], runtime.session.session_id)
        with patch("src.desktop.runtime.ImageStudioTool.run", return_value=ToolResult(
            name="ImageStudio", output={"action": "ai_edit", "artifacts": []},
        )) as run_image:
            job = runtime.start_chat("Please transform this image into a watercolor", attachments=staged)
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1], timeout=5))
        tool_input = run_image.call_args.args[0]
        self.assertEqual(tool_input["action"], "ai_edit")
        self.assertEqual(tool_input["source"], staged[0]["path"])
        runtime.provider.chat.assert_not_called()

    def test_code_feature_request_is_not_misrouted_as_image_generation(self) -> None:
        self.assertIsNone(direct_image_request("Fix the image generator feature in this application"))

    def test_uploaded_document_is_downloadable_and_backend_context_is_hidden(self) -> None:
        runtime = self._runtime()
        source = Path(self.tmp.name) / "brief.txt"
        source.write_text("confidential attachment body", encoding="utf-8")
        staged = runtime.attach_files([{"kind": "file", "path": str(source)}], runtime.session.session_id)
        self.assertIn("/api/attachments/download", staged[0]["download_url"])

        def fake_loop(*, conversation, **_kwargs):
            conversation.add_assistant_message("I read the brief.")
            return AgentLoopResult(response_text="I read the brief.", usage={}, num_turns=1)

        with patch("src.desktop.runtime.run_agent_loop", side_effect=fake_loop):
            job = runtime.start_chat("Summarize this file", attachments=staged)
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1], timeout=5))
        rich_user = next(row for row in runtime.session.export_messages() if row["role"] == "user")
        text = next(block["text"] for block in rich_user["content"] if block.get("type") == "text")
        attachment = next(block for block in rich_user["content"] if block.get("type") == "attachment")
        self.assertEqual(text, "Summarize this file")
        self.assertEqual(attachment["name"], "brief.txt")
        self.assertIn("/api/attachments/download", attachment["download_url"])

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
        self.assertIn("ToolSearch", names)
        for tool in tools:
            self.assertEqual(tool["input_schema"].get("type"), "object", tool["name"])
        self.assertEqual(runtime.status()["version"], "0.4.9")
        self.assertTrue(runtime.status()["standalone"])

    def test_local_chat_route_skips_tools_for_conversation_and_focuses_actions(self) -> None:
        lightweight, tools = local_chat_route("Tell me a short joke about robots")
        self.assertTrue(lightweight)
        self.assertEqual(tools, set())

        lightweight, tools = local_chat_route("Fix the Python project and run its tests")
        self.assertFalse(lightweight)
        self.assertIn("ToolSearch", tools)
        self.assertIn("Read", tools)
        self.assertIn("Edit", tools)
        self.assertIn("Bash", tools)
        self.assertNotIn("SendUserMessage", tools)

        lightweight, tools = local_chat_route("Open Chrome and take a desktop screenshot")
        self.assertFalse(lightweight)
        self.assertIn("DeviceControl", tools)

        lightweight, tools = local_chat_route("What is shown here?", [MagicMock()])
        self.assertFalse(lightweight)
        self.assertIn("ImageStudio", tools)

    def test_ordinary_local_chat_uses_lightweight_one_turn_loop(self) -> None:
        runtime = self._runtime()
        runtime.provider_name = "local"
        captured = {}

        def fake_loop(*, conversation, **kwargs):
            captured.update(kwargs)
            conversation.add_assistant_message("Fast local reply")
            return AgentLoopResult(
                response_text="Fast local reply",
                usage={"input_tokens": 12, "output_tokens": 3},
                num_turns=1,
            )

        with patch("src.desktop.runtime.run_agent_loop", side_effect=fake_loop):
            job = runtime.start_chat("Hello Jonathan, how are you?")
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1], timeout=5))

        self.assertTrue(captured["lightweight"])
        self.assertEqual(captured["max_turns"], 1)
        self.assertIsNone(captured["selected_tool_names"])
        events, _ = runtime.drain_events(job)
        self.assertTrue(any(event.get("type") == "done" and event.get("text") == "Fast local reply" for event in events))

    def test_actionable_local_chat_receives_focused_tools(self) -> None:
        runtime = self._runtime()
        runtime.provider_name = "local"
        captured = {}

        def fake_loop(*, conversation, **kwargs):
            captured.update(kwargs)
            conversation.add_assistant_message("Project checked")
            return AgentLoopResult(response_text="Project checked", usage={}, num_turns=1)

        with patch("src.desktop.runtime.run_agent_loop", side_effect=fake_loop):
            job = runtime.start_chat("Inspect this repo, fix app.py, and run tests")
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1], timeout=5))

        self.assertFalse(captured["lightweight"])
        self.assertEqual(captured["max_turns"], 12)
        self.assertIn("Read", captured["selected_tool_names"])
        self.assertIn("Edit", captured["selected_tool_names"])
        self.assertIn("Bash", captured["selected_tool_names"])

    def test_schema_400_retries_same_turn_without_tools(self) -> None:
        runtime = self._runtime()

        class Schema400(RuntimeError):
            status_code = 400
            body = {"error": {"message": "tools.17.custom.input_schema.type: Field required"}}

        runtime.provider.chat.side_effect = [
            Schema400("Error code: 400 - tools.17.custom.input_schema.type: Field required"),
            ChatResponse(
                content="hello without tools",
                model="test-model",
                usage={"input_tokens": 2, "output_tokens": 2},
                finish_reason="stop",
            ),
        ]
        job = runtime.start_chat("first desktop message")
        self.assertTrue(_wait_until(lambda: runtime.drain_events(job)[1]))
        events, done = runtime.drain_events(job)
        self.assertTrue(done)
        self.assertTrue(any(ev.get("type") == "done" and "hello without tools" in str(ev.get("text")) for ev in events))
        self.assertGreaterEqual(runtime.provider.chat.call_count, 2)
        last = runtime.provider.chat.call_args_list[-1]
        self.assertFalse(last.kwargs.get("tools"))

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

    def test_remove_chat_hides_sidebar_but_keeps_session_file_and_memory(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("Retain this private project history")
        saved = runtime.save_session()
        session_file = self.home / ".clawd" / "sessions" / f"{saved['session_id']}.json"
        self.assertTrue(session_file.exists())

        result = runtime.remove_session(saved["session_id"])

        self.assertTrue(result["retained_in_memory"])
        self.assertTrue(session_file.exists())
        self.assertIsNotNone(Session.load(saved["session_id"]))
        self.assertNotIn(saved["session_id"], {row["session_id"] for row in runtime.list_sessions()})
        self.assertIn(saved["session_id"], {row["session_id"] for row in Session.list_sessions()})
        self.assertNotEqual(runtime.session.session_id, saved["session_id"])

    def test_project_location_preview_and_packaged_download(self) -> None:
        runtime = self._runtime()
        downloads = Path(self.tmp.name) / "chosen-projects"
        configured = runtime.set_projects_dir(downloads)
        self.assertEqual(Path(configured["projects_dir"]), downloads.resolve())
        (self.workspace / "index.html").write_text("<h1>Live preview</h1>", encoding="utf-8")
        (self.workspace / "app.js").write_text("console.log('ok')", encoding="utf-8")

        preview = runtime.preview_info()
        self.assertEqual(preview["entry"], "index.html")
        self.assertIn("app.js", preview["files"])
        self.assertEqual(runtime.resolve_preview_path("index.html").read_text(encoding="utf-8"), "<h1>Live preview</h1>")

        packaged = runtime.package_workspace()
        artifact = packaged["artifact"]
        self.assertTrue(artifact["name"].endswith(".zip"))
        self.assertTrue(runtime.resolve_artifact(artifact["id"]).exists())
        self.assertIn("/api/artifacts/download", artifact["download_url"])

    def test_artifact_publish_falls_back_when_selected_location_is_not_writable(self) -> None:
        runtime = self._runtime()
        requested = Path(self.tmp.name) / "selected-projects"
        fallback = Path(self.tmp.name) / "durable-fallback"
        runtime.set_projects_dir(requested)
        runtime._artifact_fallback_dir = fallback
        source = self.workspace / "generated.png"
        source.write_bytes(b"generated-image")
        real_copy = __import__("shutil").copy2

        def guarded_copy(src, dst, *args, **kwargs):
            if Path(dst).parent == requested / "Jonathan Ai Downloads":
                raise PermissionError("selected folder became read-only")
            return real_copy(src, dst, *args, **kwargs)

        with patch("src.desktop.runtime.shutil.copy2", side_effect=guarded_copy):
            artifact = runtime._publish_artifact(source)

        self.assertEqual(runtime.artifacts_dir, fallback)
        self.assertTrue(runtime.resolve_artifact(artifact["id"]).is_file())
        self.assertEqual(runtime.resolve_artifact(artifact["id"]).read_bytes(), b"generated-image")

    def test_conversation_agents_run_simultaneously_without_session_crossover(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("agent A seed")
        agent_a = runtime.save_session()["session_id"]
        agent_b = runtime.new_session()["session_id"]
        barrier = threading.Barrier(2)

        def fake_loop(*, conversation, **_kwargs):
            user_text = next(
                str(message.content)
                for message in reversed(conversation.messages)
                if message.role == "user"
            )
            barrier.wait(timeout=3)
            conversation.add_assistant_message(f"answer for {user_text}")
            return AgentLoopResult(
                response_text=f"answer for {user_text}",
                usage={"input_tokens": 1, "output_tokens": 1},
                num_turns=1,
            )

        with patch("src.desktop.runtime.run_agent_loop", side_effect=fake_loop):
            job_a = runtime.start_chat("request A", session_id=agent_a)
            job_b = runtime.start_chat("request B", session_id=agent_b)
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job_a)[1], timeout=5))
            self.assertTrue(_wait_until(lambda: runtime.drain_events(job_b)[1], timeout=5))

        text_a = json.dumps(runtime.peek_session(agent_a)["messages"])
        text_b = json.dumps(runtime.peek_session(agent_b)["messages"])
        self.assertIn("answer for request A", text_a)
        self.assertNotIn("request B", text_a)
        self.assertIn("answer for request B", text_b)
        self.assertNotIn("request A", text_b)
        self.assertNotEqual(runtime._agent_for_session(agent_a).tool_context, runtime._agent_for_session(agent_b).tool_context)

    def test_agent_can_cross_view_other_instance_when_needed(self) -> None:
        runtime = self._runtime()
        runtime.session.conversation.add_user_message("cross-view fact from A")
        agent_a = runtime.save_session()["session_id"]
        agent_b = runtime.new_session()["session_id"]
        context = runtime._agent_for_session(agent_b).tool_context
        result = runtime.tool_registry.dispatch(
            ToolCall(name="AgentInstances", input={"action": "read", "session_id": agent_a}),
            context,
        )
        self.assertFalse(result.is_error)
        self.assertIn("cross-view fact from A", json.dumps(result.output))

    def test_terminal_discovers_and_executes_installed_shell(self) -> None:
        terminals = discover_terminals()
        self.assertTrue(terminals)
        shell = "cmd" if any(item["name"] == "cmd" for item in terminals) else "auto"
        context = ToolContext(workspace_root=self.workspace)
        result = TerminalTool().run({"command": "echo terminal-ok", "shell": shell}, context)
        self.assertFalse(result.is_error, result.output)
        self.assertIn("terminal-ok", result.output["stdout"])

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
        ready_req = urllib.request.Request(
            f"{server.url}api/ready",
            headers={"X-Clawd-Token": server.token},
        )
        ready = json.loads(urllib.request.urlopen(ready_req, timeout=2).read())
        self.assertTrue(ready["ok"])
        self.assertEqual(ready["version"], "0.4.9")

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
        self.assertIn("0.4.9", html)
        self.assertIn("session-menu", html)
        self.assertIn("working-robot", html)
        self.assertIn("preview-pane", html)
        self.assertIn("package-project", html)
        self.assertIn("pick-projects", html)
        self.assertIn("session-menu-remove", html)
        self.assertIn("app.js", html)

    def test_preview_and_artifact_download_require_token_and_serve_files(self) -> None:
        from PIL import Image

        runtime = DesktopRuntime(workspace=self.workspace)
        downloads = Path(self.tmp.name) / "downloads"
        runtime.set_projects_dir(downloads)
        (self.workspace / "index.html").write_text("<h1>Preview works</h1>", encoding="utf-8")
        artifact = runtime.package_workspace()["artifact"]
        server = DesktopServer(runtime, host="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)

        preview_req = urllib.request.Request(
            f"{server.url}preview/index.html",
            headers={"X-Clawd-Token": server.token},
        )
        self.assertIn(b"Preview works", urllib.request.urlopen(preview_req, timeout=2).read())
        download_req = urllib.request.Request(
            f"{server.url}{artifact['download_url']}",
            headers={"X-Clawd-Token": server.token},
        )
        with urllib.request.urlopen(download_req, timeout=2) as response:
            self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
            self.assertTrue(response.read().startswith(b"PK"))

        image_path = self.workspace / "generated.png"
        Image.new("RGB", (12, 8), "purple").save(image_path)
        image_artifact = runtime._publish_session_artifact(
            runtime.session.session_id,
            image_path,
            "generated.png",
        )
        runtime.session.save()
        self.assertTrue(image_artifact["is_image"])
        self.assertIn("/api/artifacts/view", image_artifact["view_url"])
        rich = runtime.session.export_messages()
        artifact_block = next(
            block
            for row in rich
            for block in (row["content"] if isinstance(row["content"], list) else [])
            if block.get("type") == "artifact"
        )
        self.assertEqual(artifact_block["name"], image_artifact["name"])
        self.assertEqual(Session.load(runtime.session.session_id).media_items[0]["name"], image_artifact["name"])

        view_req = urllib.request.Request(
            f"{server.url}{image_artifact['view_url']}",
            headers={"X-Clawd-Token": server.token},
        )
        with urllib.request.urlopen(view_req, timeout=2) as response:
            self.assertIn("inline", response.headers.get("Content-Disposition", ""))
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertTrue(response.read().startswith(b"\x89PNG"))

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
