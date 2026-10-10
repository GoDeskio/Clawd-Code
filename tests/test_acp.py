"""Local ACP hand-off: approval, shell guard, settings, and a fake runner."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.acp.runners import load_runners, public_runners, settings_path, update_runners
from src.acp.service import delegate_task, format_acp_command, resolve_folder
from src.command_system.builtins import execute_command_sync
from src.command_system.engine import create_command_context
from src.desktop.runtime import ChatJob, DesktopRuntime, _HELP_TEXT
from src.desktop.server import DesktopServer
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.acp import AcpTool

ROOT = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).resolve().parent / "fake_acp_runner.py"
SECRET = "sk-ant-" + ("a" * 24)


class AcpTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.acp = self.root / "acp"
        self.project = self.root / "project"
        self.project.mkdir()
        self._env = patch.dict(
            os.environ,
            {"JONATHAN_ACP_DIR": str(self.acp), "JONATHAN_USER": "acp-test"},
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self.tmp.cleanup()

    def _enable_fake(self, runner: str = "opencode") -> None:
        update_runners(
            [{
                "id": runner,
                "enabled": True,
                "command": sys.executable,
                "args": [str(FAKE)],
            }],
            self.acp,
        )

    def _context(self, *, gate: bool = False) -> ToolContext:
        ctx = ToolContext(workspace_root=self.project, acp_dir=self.acp)
        ctx.gate_destructive_tools = gate
        return ctx


class TestRunnerSettings(AcpTestCase):
    def test_runners_start_disabled_and_stay_per_user(self) -> None:
        listed = format_acp_command("list", directory=self.acp, user_id="alice")
        self.assertIn("opencode", listed)
        self.assertIn("disabled", listed)
        update_runners(
            [{"id": "zed", "enabled": True, "command": "/usr/bin/zed", "args": ["acp"]}],
            self.acp,
            user_id="alice",
        )
        alice = load_runners(self.acp, user_id="alice")["zed"]
        bob = load_runners(self.acp, user_id="bob")["zed"]
        self.assertTrue(alice.enabled)
        self.assertEqual(alice.command, "/usr/bin/zed")
        self.assertFalse(bob.enabled)
        self.assertEqual(bob.command, "zed")
        mode = settings_path(self.acp, user_id="alice").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_empty_command_resets_to_the_local_default(self) -> None:
        view = update_runners(
            [{"id": "opencode", "enabled": True, "command": "", "args": "rm -rf /"}],
            self.acp,
        )
        row = next(item for item in view["runners"] if item["id"] == "opencode")
        self.assertEqual(row["command"], "opencode")
        self.assertEqual(row["args"], ["acp"])
        self.assertNotIn("token", row)
        self.assertNotIn("api_key", row)

    def test_unknown_runner_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            update_runners([{"id": "kimi", "enabled": True}], self.acp)
        server = DesktopServer(DesktopRuntime(workspace=self.project, permission_timeout_s=1.0))
        status, body = server.handle_api("GET", "/api/acp", {}, {})
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in body["runners"]], ["opencode", "claude_code", "codex", "zed"])
        with self.assertRaises(ValueError):
            server.handle_api("POST", "/api/acp", {}, {"runners": [{"id": "nope"}]})


class TestApprovalAndGuard(AcpTestCase):
    def test_disabled_missing_and_root_never_start(self) -> None:
        tool = AcpTool()
        ctx = self._context(gate=True)

        def explode(*_args, **_kwargs):
            raise AssertionError("runner started")

        with patch("src.acp.protocol.subprocess.Popen", explode):
            disabled = tool.check_permissions(
                {"runner": "opencode", "folder": str(self.project), "task": "edit"},
                ctx,
            )
            self.assertEqual(disabled.behavior, PermissionBehavior.DENY)
            self.assertIn("not enabled", (disabled.message or "").lower())

            self._enable_fake()
            missing = tool.check_permissions(
                {"runner": "opencode", "folder": str(self.root / "missing"), "task": "edit"},
                ctx,
            )
            self.assertEqual(missing.behavior, PermissionBehavior.DENY)
            self.assertIn("not found", (missing.message or "").lower())

            with self.assertRaises(ValueError):
                resolve_folder("/")
            root = tool.check_permissions(
                {"runner": "opencode", "folder": "/", "task": "edit"},
                ctx,
            )
            self.assertEqual(root.behavior, PermissionBehavior.DENY)
            self.assertIn("filesystem root", (root.message or "").lower())

    def test_gate_without_a_handler_does_not_start(self) -> None:
        self._enable_fake()
        ctx = self._context(gate=True)
        registry = ToolRegistry(tools=[AcpTool()])
        with patch("src.acp.protocol.subprocess.Popen", side_effect=AssertionError("runner started")):
            result = registry.dispatch(
                ToolCall(
                    name="Acp",
                    input={"runner": "opencode", "folder": str(self.project), "task": "edit"},
                ),
                ctx,
            )
        self.assertTrue(result.is_error)
        self.assertIn(str(self.project), str(result.output))
        self.assertFalse((self.project / "delegated.txt").exists())

    def test_ask_names_the_folder_and_command(self) -> None:
        self._enable_fake()
        decision = AcpTool().check_permissions(
            {"runner": "opencode", "folder": str(self.project), "task": "edit"},
            self._context(gate=True),
        )
        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        message = decision.message or ""
        self.assertIn(str(self.project), message)
        self.assertIn(sys.executable, message)
        self.assertIn(FAKE.name, message)

    def test_dangerous_command_still_asks_with_a_session_grant(self) -> None:
        update_runners(
            [{
                "id": "codex",
                "enabled": True,
                "command": "bash",
                "args": ["-c", "rm -rf /"],
            }],
            self.acp,
        )
        ctx = self._context(gate=True)
        ctx.session_grants.add("*")
        decision = AcpTool().check_permissions(
            {"runner": "codex", "folder": str(self.project), "task": "edit"},
            ctx,
        )
        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertIn(str(self.project), decision.message or "")
        self.assertIn("rm", (decision.message or "").lower())
        ran = AcpTool().run(
            {"runner": "codex", "folder": str(self.project), "task": "edit"},
            ctx,
        )
        self.assertTrue(ran.is_error)
        self.assertFalse((self.project / "delegated.txt").exists())


class TestFakeRunner(AcpTestCase):
    def test_streams_progress_and_lists_changed_files(self) -> None:
        self._enable_fake()
        progress: list[str] = []
        ctx = self._context(gate=False)
        ctx.progress_handler = progress.append
        tool = AcpTool()
        payload = {"runner": "opencode", "folder": str(self.project), "task": SECRET}
        decision = tool.check_permissions(payload, ctx)
        self.assertEqual(decision.behavior, PermissionBehavior.ALLOW)
        result = tool.run(decision.updated_input or payload, ctx)
        self.assertFalse(result.is_error)
        text = result.output["text"]
        self.assertIn("Changed files:", text)
        self.assertIn("delegated.txt", text)
        self.assertIn("OpenCode", text)
        self.assertNotIn(SECRET, text)
        self.assertTrue(any("Writing delegated.txt" in line for line in progress))
        self.assertNotIn(SECRET, "\n".join(progress))
        self.assertTrue((self.project / "delegated.txt").is_file())

    def test_command_list_roundtrip(self) -> None:
        context = create_command_context(self.project)
        ok, text, error = execute_command_sync("acp", "list", context)
        self.assertTrue(ok, error)
        self.assertIn("claude_code", text or "")
        self.assertIn("disabled", text or "")
        blocked = format_acp_command(
            f"run opencode {self.project} hello",
            directory=self.acp,
        )
        self.assertIn("not enabled", blocked.lower())

    def test_cli_list(self) -> None:
        from io import StringIO

        from src.cli import handle_acp

        buf = StringIO()
        with patch("sys.stdout", buf):
            code = handle_acp(argparse.Namespace(acp_command="list"))
        self.assertEqual(code, 0)
        self.assertIn("Zed", buf.getvalue())


class TestUiAndRegistry(AcpTestCase):
    def test_help_panel_and_skill_index(self) -> None:
        html = (ROOT / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "src" / "desktop" / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("/acp", _HELP_TEXT)
        for label in ("Coding agents", "OpenCode", "Claude Code", "Codex", "Zed", "acp-save"):
            self.assertIn(label, html)
        self.assertNotIn("GLM", html)
        self.assertIn('input[type="checkbox"]', css)
        names = [spec.name for spec in build_default_registry(include_user_tools=False).list_specs()]
        self.assertEqual(names[17], "Skill")
        self.assertGreater(names.index("Acp"), 17)

    def test_import_does_not_load_a_network_acp_library(self) -> None:
        import src.acp.protocol
        import src.acp.service

        self.assertNotIn("acp", sys.modules)
        self.assertNotIn("agent_client_protocol", sys.modules)
        self.assertIn("src.acp.protocol", sys.modules)
        self.assertIn("src.acp.service", sys.modules)

    def test_slash_streams_progress_after_approval(self) -> None:
        self._enable_fake()
        runtime = DesktopRuntime(workspace=self.project, permission_timeout_s=1.0)
        runtime.tool_context.acp_dir = self.acp
        asked: list[str] = []

        def allow(tool_name: str, message: str, suggestion: str | None) -> tuple[bool, bool]:
            del tool_name, suggestion
            asked.append(message)
            return True, False

        runtime.tool_context.permission_handler = allow
        job = ChatJob(job_id="acp-job")
        runtime._run_acp_slash(job, f"run opencode {self.project} write a note")
        self.assertTrue(job.done)
        kinds = [event["type"] for event in job.events]
        self.assertIn("acp_progress", kinds)
        self.assertIn("done", kinds)
        self.assertTrue(asked)
        self.assertIn(str(self.project), asked[0])
        done = next(event for event in job.events if event["type"] == "done")
        self.assertIn("delegated.txt", done["text"])


class TestDirectDelegate(AcpTestCase):
    def test_delegate_masks_runner_text(self) -> None:
        self._enable_fake()
        text = delegate_task(
            runner_id="opencode",
            folder=str(self.project),
            task=SECRET,
            directory=self.acp,
        )
        self.assertIn("delegated.txt", text)
        self.assertNotIn(SECRET, text)
        view = public_runners(self.acp)
        blob = str(view)
        self.assertNotIn("SECRET", blob)
        self.assertNotIn(SECRET, blob)


if __name__ == "__main__":
    unittest.main()
