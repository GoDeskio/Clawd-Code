"""Persistent scheduler: Phoenix time, text and agent modes, missed runs."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.command_system import create_command_context, execute_command_sync
from src.providers.base import ChatResponse
from src.scheduler.expr import next_after, parse_trigger, zone_or_default
from src.scheduler.service import (
    DEFAULT_TIMEZONE,
    catch_up,
    create_job,
    delete_job,
    list_jobs,
    list_logs,
    run_now,
    scheduler_db_path,
    set_enabled,
)
from src.tool_system.context import ToolContext
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.bash import BashTool
from src.tool_system.tools.cron import CronCreateTool, CronDeleteTool, CronListTool

PHOENIX = ZoneInfo("America/Phoenix")


class ScriptedProvider:
    def __init__(self, command: str) -> None:
        self.command = command
        self.calls = 0
        self.model = "test"

    def chat(self, messages, tools=None, **kwargs):
        del messages, tools, kwargs
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content="",
                model="test",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="tool_use",
                tool_uses=[{"id": "t1", "name": "Bash", "input": {"command": self.command}}],
            )
        return ChatResponse(
            content="done",
            model="test",
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="stop",
            tool_uses=None,
        )

    def chat_stream(self, *args, **kwargs):
        raise NotImplementedError


class TestScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ctx = ToolContext(workspace_root=self.root, scheduler_dir=self.root / "scheduler")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _as(self, user: str):
        return patch("src.scheduler.service.current_user_id", return_value=user)

    def test_phoenix_is_the_default_and_monday_is_unix_weekday(self) -> None:
        self.assertEqual(DEFAULT_TIMEZONE, "America/Phoenix")
        now = datetime(2026, 10, 10, 8, 0, tzinfo=PHOENIX)
        job = create_job(self.ctx, cron="0 9 * * *", prompt="morning note", now=now)
        self.assertEqual(job["timezone"], "America/Phoenix")
        self.assertTrue(job["next_run_at"].startswith("2026-10-10T16:00:00"))
        self.assertEqual(self.ctx.crons, {})
        monday = create_job(
            self.ctx,
            cron="0 9 * * 1",
            prompt="monday note",
            now=datetime(2026, 10, 10, 10, 0, tzinfo=PHOENIX),
        )
        self.assertTrue(monday["next_run_at"].startswith("2026-10-12T16:00:00"))
        trigger = parse_trigger("0 9 1 * 1", zone_or_default(None))
        self.assertIsNotNone(next_after(trigger, datetime(2026, 10, 1, 8, 0, tzinfo=PHOENIX), PHOENIX))

    def test_text_run_now_and_missed_run_outside_grace(self) -> None:
        created = datetime(2026, 10, 10, 8, 0, tzinfo=PHOENIX)
        job = create_job(
            self.ctx,
            cron="0 9 * * *",
            prompt="stand up",
            task_type="text",
            now=created,
        )
        early = run_now(self.ctx, job["id"], now=created)
        self.assertEqual(early["task_type"], "text")
        self.assertEqual(early["output"], "stand up")
        missed_at = datetime(2026, 10, 10, 11, 0, tzinfo=PHOENIX)
        result = catch_up(self.ctx, now=missed_at)
        self.assertIn(job["id"], result["missed"])
        self.assertNotIn(job["id"], result["ran"])
        logs = list_logs(self.ctx, job["id"])
        self.assertTrue(any(row["status"] == "missed" and "grace" in row["message"] for row in logs))
        self.assertEqual(list_jobs(self.ctx)[0]["last_status"], "missed")
        listed = list_jobs(self.ctx)[0]
        self.assertTrue(listed["next_run_at"].startswith("2026-10-11T16:00:00"))

    def test_catch_up_inside_grace_delivers_text_once(self) -> None:
        job = create_job(
            self.ctx,
            cron="0 9 * * *",
            prompt="drink water",
            task_type="text",
            now=datetime(2026, 10, 10, 8, 0, tzinfo=PHOENIX),
        )
        due = datetime(2026, 10, 10, 9, 0, 30, tzinfo=PHOENIX)
        result = catch_up(self.ctx, now=due)
        self.assertEqual(result["ran"], [job["id"]])
        self.assertEqual(result["errors"], [])
        logs = list_logs(self.ctx, job["id"])
        self.assertTrue(any(row["status"] == "ok" and "drink water" in row["message"] for row in logs))
        again = catch_up(self.ctx, now=due + timedelta(seconds=5))
        self.assertEqual(again["ran"], [])

    def test_enable_disable_delete_and_user_isolation(self) -> None:
        with self._as("ada"):
            ada = create_job(self.ctx, cron="*/15 * * * *", prompt="Ada pencils", name="pencils")
            ada_id = ada["id"]
            disabled = set_enabled(self.ctx, ada_id, False)
            self.assertFalse(disabled["enabled"])
        with self._as("bob"):
            self.assertEqual(list_jobs(self.ctx), [])
            self.assertFalse(delete_job(self.ctx, ada_id))
            bob_blob = scheduler_db_path(self.ctx).read_bytes()
        self.assertNotIn(b"pencils", bob_blob)
        with self._as("ada"):
            self.assertEqual(list_jobs(self.ctx)[0]["id"], ada_id)
            due = datetime.now(PHOENIX) + timedelta(days=1)
            self.assertEqual(catch_up(self.ctx, now=due)["ran"], [])
            self.assertTrue(delete_job(self.ctx, ada_id))
            self.assertEqual(list_jobs(self.ctx), [])
            self.assertTrue(any(row["status"] == "deleted" for row in list_logs(self.ctx, ada_id)))

    def test_secrets_never_land_in_sqlite(self) -> None:
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIBexamplekeymaterialnotreal1234567890ABCD\n"
            "-----END RSA PRIVATE KEY-----"
        )
        create_job(
            self.ctx,
            cron="0 8 * * *",
            prompt=f"keep {pem} password=hunter2hunter2 and my password is spokenphrase99",
        )
        blob = scheduler_db_path(self.ctx).read_bytes()
        for secret in (
            b"examplekeymaterialnotreal",
            b"BEGIN RSA PRIVATE KEY",
            b"hunter2hunter2",
            b"spokenphrase99",
        ):
            self.assertNotIn(secret, blob)

    def test_agent_task_uses_shell_guard_and_approval(self) -> None:
        allowed = self.root / "allowed.txt"
        blocked = self.root / "blocked.txt"
        approved = self.root / "approved.txt"
        self.ctx.provider = ScriptedProvider(f"echo hello > {allowed}")
        self.ctx.tool_registry = ToolRegistry([BashTool()])
        job = create_job(self.ctx, cron="0 12 * * *", prompt="write the file", task_type="agent")
        ran = run_now(self.ctx, job["id"])
        self.assertEqual(ran["status"], "ok")
        self.assertEqual(allowed.read_text(encoding="utf-8").strip(), "hello")
        self.assertEqual(self.ctx.provider.calls, 2)

        self.ctx.provider = ScriptedProvider(f"echo rm > {blocked}")
        blocked_job = create_job(self.ctx, cron="0 12 * * *", prompt="do not wipe", task_type="agent")
        run_now(self.ctx, blocked_job["id"])
        self.assertFalse(blocked.exists())

        self.ctx.provider = ScriptedProvider(f"echo rm > {approved}")
        self.ctx.permission_handler = lambda tool_name, message, suggestion: (True, False)
        approved_job = create_job(self.ctx, cron="0 12 * * *", prompt="approve the echo", task_type="agent")
        run_now(self.ctx, approved_job["id"])
        self.assertEqual(approved.read_text(encoding="utf-8").strip(), "rm")

    def test_text_mode_does_not_execute_the_prompt(self) -> None:
        marker = self.root / "not-run.txt"
        self.ctx.provider = ScriptedProvider(f"echo hello > {marker}")
        self.ctx.tool_registry = ToolRegistry([BashTool()])
        job = create_job(
            self.ctx,
            cron="0 12 * * *",
            prompt=f"echo hello > {marker}",
            task_type="text",
        )
        run_now(self.ctx, job["id"])
        self.assertFalse(marker.exists())
        self.assertEqual(self.ctx.provider.calls, 0)

    def test_tools_and_commands_roundtrip(self) -> None:
        created = CronCreateTool().run({"cron": "*/5 * * * *", "prompt": "ping"}, self.ctx).output
        listed = CronListTool().run({}, self.ctx).output
        self.assertEqual(len(listed["jobs"]), 1)
        self.assertTrue(scheduler_db_path(self.ctx).is_file())
        context = create_command_context(
            workspace_root=self.root,
            conversation=object(),
            cost_tracker=object(),
            history=object(),
        )
        with patch("src.scheduler.service.scheduler_dir", return_value=self.root / "scheduler"):
            success, text, error = execute_command_sync("cron", "list", context)
            self.assertTrue(success, error)
            self.assertIn(created["id"], text)
            success, ran, error = execute_command_sync("cron", f"run {created['id']}", context)
            self.assertTrue(success, error)
            self.assertIn("ping", ran)
            success, disabled, error = execute_command_sync("cron", f"disable {created['id']}", context)
            self.assertTrue(success, error)
            self.assertIn("disabled", disabled)
            success, enabled, error = execute_command_sync("cron", f"enable {created['id']}", context)
            self.assertTrue(success, error)
            self.assertIn("enabled", enabled)
            success, logs, error = execute_command_sync("cron", "logs", context)
            self.assertTrue(success, error)
            self.assertIn("created", logs)
            from src.cli import main

            buf = io.StringIO()
            with patch.object(sys, "argv", ["clawd", "cron", "list"]), patch("sys.stdout", buf):
                code = main()
            self.assertEqual(code, 0)
            self.assertIn("ping", buf.getvalue())
        deleted = CronDeleteTool().run({"id": created["id"]}, self.ctx).output
        self.assertTrue(deleted["success"])
        self.assertEqual(CronListTool().run({}, self.ctx).output["jobs"], [])

    def test_interval_and_invalid_schedule(self) -> None:
        now = datetime(2026, 10, 10, 8, 0, tzinfo=PHOENIX)
        job = create_job(self.ctx, cron="interval:3600", prompt="hourly", now=now)
        self.assertTrue(job["next_run_at"].startswith("2026-10-10T16:00:00"))
        with self.assertRaises(ValueError):
            create_job(self.ctx, cron="not a schedule", prompt="nope")
        with self.assertRaises(ValueError):
            create_job(self.ctx, cron="agently:mailbox", prompt="nope")
        with self.assertRaises(ValueError):
            create_job(self.ctx, cron="*/5 * * * *", prompt="x", task_type="email")
