"""Shared agent memory stays local and is injected as a compact brief."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.memory import (
    add_fact,
    build_memory_brief,
    extract_facts,
    remember_turn,
    sanitize_memory_text,
)


class TestMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.home_patch = patch("src.agent.memory.Path.home", return_value=self.home)
        self.home_patch.start()

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.tmp.cleanup()

    def test_extract_and_brief_excludes_current_chat(self) -> None:
        self.assertIn("repo is clawd", extract_facts("Remember that the repo is clawd")[0].lower())
        remember_turn(
            session_id="chat-a",
            title="Setup",
            user_text="Remember that the mascot is a robot sketch.",
            assistant_text="Noted.",
        )
        brief_b = build_memory_brief(exclude_session_id="chat-b")
        self.assertIn("robot sketch", brief_b)
        self.assertIn("Setup", brief_b)
        brief_a = build_memory_brief(exclude_session_id="chat-a")
        self.assertIn("robot sketch", brief_a)
        self.assertNotIn("Setup:", brief_a)

    def test_redacts_secrets(self) -> None:
        cleaned = sanitize_memory_text("token sk-abcdefghijklmnopqrstuvwxyz")
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", cleaned)
        self.assertIn("[redacted]", cleaned)
        add_fact("api_key=supersecretvalue123", source_session="x")
        brief = build_memory_brief()
        self.assertNotIn("supersecretvalue123", brief)

    def test_parallel_workers_do_not_lose_index_entries(self) -> None:
        from src.agent.memory import list_conversation_index, upsert_conversation_index

        def write(index: int) -> None:
            upsert_conversation_index(
                session_id=f"worker-{index}",
                title=f"Worker {index}",
                summary=f"Result {index}",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(16)))
        ids = {row["session_id"] for row in list_conversation_index()}
        self.assertTrue({f"worker-{index}" for index in range(16)}.issubset(ids))


if __name__ == "__main__":
    unittest.main()
