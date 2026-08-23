"""Internal planner/workers stay isolated and do not need other products."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.agent.multi_agent import plan_subtasks, run_internal_workers
from src.providers.base import ChatResponse
from src.tool_system.defaults import build_default_registry


class TestMultiAgent(unittest.TestCase):
    def test_plan_splits_then_clauses(self) -> None:
        parts = plan_subtasks("Research the mascot then write a summary")
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(any("mascot" in part.lower() for part in parts))

    def test_workers_run_without_tools_and_share_memory_not_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            provider = MagicMock()
            provider.chat.return_value = ChatResponse(
                content="worker done",
                model="test",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="stop",
            )
            with patch("src.agent.memory.Path.home", return_value=home):
                result = run_internal_workers(
                    provider=provider,
                    goal="Look up the logo then draft the README blurb",
                    parent_session_id="chat-parent",
                )
            self.assertTrue(result["ok"])
            self.assertGreaterEqual(len(result["workers"]), 2)
            self.assertNotEqual(result["workers"][0]["worker_id"], result["workers"][1]["worker_id"])
            for call in provider.chat.call_args_list:
                kwargs = call.kwargs
                self.assertFalse(kwargs.get("tools"))

    def test_registry_includes_spawn_workers_classic_schema(self) -> None:
        from src.tool_system.schema_sanitize import serialize_tools_for_provider

        tools = serialize_tools_for_provider(
            build_default_registry(include_user_tools=False),
            include_optional_connectors=False,
        )
        names = [item["name"] for item in tools]
        self.assertIn("SpawnWorkers", names)
        spawn = next(item for item in tools if item["name"] == "SpawnWorkers")
        self.assertEqual(spawn["input_schema"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
