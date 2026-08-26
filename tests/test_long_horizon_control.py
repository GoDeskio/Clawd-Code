from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.errors import ToolInputError
from src.tool_system.tools.long_horizon_control import LongHorizonControlTool


class TestLongHorizonControl(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"JONATHAN_GOAL_STORE": str(self.root / "goals")})
        self.environment.start()
        self.context = ToolContext(workspace_root=self.root)
        self.tool = LongHorizonControlTool()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def test_registered_with_valid_object_schema(self) -> None:
        registered = build_default_registry(include_user_tools=False).get("LongHorizonControl")
        self.assertIsNotNone(registered)
        self.assertEqual(registered.spec().input_schema["type"], "object")

    def test_gate_blocks_then_goal_completes_with_utf8_evidence(self) -> None:
        created = self.tool.run({"action": "create", "objective": "Préparer café", "max_turns": 3}, self.context).output
        goal_id = created["id"]
        todo = self.tool.run({
            "action": "add_todo", "goal_id": goal_id, "title": "Vérifier ✓",
        }, self.context).output["todo"]
        gate = self.tool.run({
            "action": "add_gate", "goal_id": goal_id, "title": "Human approves",
        }, self.context).output["gate"]
        decision = self.tool.run({"action": "continuation", "goal_id": goal_id}, self.context).output
        self.assertFalse(decision["may_continue"])

        self.tool.run({
            "action": "resolve_gate", "goal_id": goal_id, "gate_id": gate["id"], "resolution": "Approved",
        }, self.context)
        self.tool.run({
            "action": "claim_todo", "goal_id": goal_id, "todo_id": todo["id"], "agent_id": "agent-one",
        }, self.context)
        self.tool.run({
            "action": "complete_todo", "goal_id": goal_id, "todo_id": todo["id"],
            "agent_id": "agent-one", "summary": "Confirmed café output", "reference": "tests/report.json",
        }, self.context)
        completed = self.tool.run({"action": "close", "goal_id": goal_id}, self.context).output
        self.assertEqual(completed["status"], "completed")
        persisted = (self.root / "goals" / f"{goal_id}.json").read_text(encoding="utf-8")
        self.assertIn("Préparer café", persisted)
        self.assertIn("Confirmed café output", persisted)

    def test_claim_lease_and_bounded_turns_fail_closed(self) -> None:
        goal = self.tool.run({"action": "create", "objective": "Ship safely", "max_turns": 1}, self.context).output
        todo = self.tool.run({"action": "add_todo", "goal_id": goal["id"], "title": "Test"}, self.context).output["todo"]
        self.tool.run({
            "action": "claim_todo", "goal_id": goal["id"], "todo_id": todo["id"], "agent_id": "a",
        }, self.context)
        with self.assertRaises(ToolInputError):
            self.tool.run({
                "action": "claim_todo", "goal_id": goal["id"], "todo_id": todo["id"], "agent_id": "b",
            }, self.context)
        spent = self.tool.run({
            "action": "spend_turn", "goal_id": goal["id"], "todo_id": todo["id"],
            "agent_id": "a", "summary": "Ran the focused test",
        }, self.context).output
        self.assertFalse(spent["continuation"]["may_continue"])
        self.assertIn("exhausted", spent["continuation"]["reason"])

    def test_list_is_workspace_scoped_but_cross_view_is_explicit(self) -> None:
        self.tool.run({"action": "create", "objective": "Current"}, self.context)
        other = ToolContext(workspace_root=self.root / "other")
        self.tool.run({"action": "create", "objective": "Other"}, other)
        local = self.tool.run({"action": "list"}, self.context).output
        all_goals = self.tool.run({"action": "list", "include_all": True}, self.context).output
        self.assertEqual(local["count"], 1)
        self.assertEqual(all_goals["count"], 2)


if __name__ == "__main__":
    unittest.main()
