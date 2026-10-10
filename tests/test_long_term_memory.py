"""Long-term memory is local SQLite, per user, and secret-free."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.memory import (
    add_fact,
    build_memory_brief,
    current_user_id,
    delete_memory,
    extract_facts,
    format_memory_command,
    list_facts,
    list_memories,
    memory_db_path,
    recall,
    remember_turn,
)
from src.command_system import create_command_context, execute_command_sync


class TestLongTermMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.home_patch = patch("src.agent.memory.Path.home", return_value=self.home)
        self.home_patch.start()

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.tmp.cleanup()

    def _as(self, user: str):
        return patch("src.agent.memory.current_user_id", return_value=user)

    def test_extract_then_recall_in_a_later_brief(self) -> None:
        found = extract_facts("Remember that the deploy window is Tuesday.")
        self.assertTrue(any("Tuesday" in item for item in found))
        remember_turn(
            session_id="chat-a",
            title="Release",
            user_text="Remember that the deploy window is Tuesday.",
            assistant_text="I will keep that.",
        )
        matches = recall("deploy window")
        self.assertTrue(matches)
        self.assertIn("Tuesday", matches[0]["text"])
        later = build_memory_brief(exclude_session_id="chat-b")
        self.assertIn("Tuesday", later)
        self.assertIn("Release", later)
        self.assertTrue(memory_db_path().is_file())
        self.assertEqual(memory_db_path().parent, self.home / ".clawd" / "memory")
        self.assertTrue(str(memory_db_path()).endswith(f"memory-{current_user_id()}.sqlite"))

    def test_secrets_are_masked_before_they_touch_sqlite(self) -> None:
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIBexamplekeymaterialnotreal1234567890ABCD\n"
            "-----END RSA PRIVATE KEY-----"
        )
        add_fact(f"keep this {pem}")
        add_fact("note password=hunter2hunter2 end")
        add_fact("my password is spokenphrase99")
        remember_turn(
            session_id="chat-secret",
            title="Login",
            user_text="token sk-abcdefghijklmnopqrstuvwxyz",
            assistant_text="stored",
        )
        blob = memory_db_path().read_bytes()
        for secret in (
            b"examplekeymaterialnotreal",
            b"BEGIN RSA PRIVATE KEY",
            b"hunter2hunter2",
            b"spokenphrase99",
            b"sk-abcdefghijklmnopqrstuvwxyz",
        ):
            self.assertNotIn(secret, blob)
        stored = " ".join(row["text"] for row in list_memories())
        self.assertIn("[REDACTED PRIVATE KEY]", stored)
        self.assertIn("[redacted]", stored)
        self.assertNotIn("hunter2hunter2", build_memory_brief())

    def test_list_and_delete_are_limited_to_the_current_user(self) -> None:
        with self._as("ada"):
            ada = add_fact("Ada likes pencils")
            self.assertIsNotNone(ada)
            ada_id = ada["id"]
            listed = list_memories()
            self.assertEqual([row["id"] for row in listed], [ada_id])
            self.assertEqual(listed[0]["kind"], "fact")
            self.assertIn("pencils", format_memory_command("list"))
        with self._as("bob"):
            bob = add_fact("Bob likes ink")
            self.assertEqual(recall("pencils"), [])
            self.assertFalse(any("pencils" in row["text"] for row in list_memories()))
            self.assertFalse(delete_memory(ada_id))
            self.assertIn("No memory", format_memory_command(f"delete {ada_id}"))
            bob_blob = memory_db_path().read_bytes()
        self.assertNotIn(b"pencils", bob_blob)
        with self._as("ada"):
            self.assertEqual([row["id"] for row in list_memories()], [ada_id])
            self.assertIn("No memory", format_memory_command(f"delete {bob['id']}"))
            self.assertTrue(delete_memory(ada_id))
            self.assertEqual(list_memories(), [])
            self.assertEqual(recall("pencils"), [])
        with self._as("bob"):
            self.assertEqual([row["id"] for row in list_memories()], [bob["id"]])

    def test_legacy_json_imports_once_and_strips_secrets(self) -> None:
        folder = self.home / ".clawd" / "memory"
        folder.mkdir(parents=True)
        (folder / "facts.json").write_text(
            json.dumps(
                {
                    "facts": [
                        {
                            "id": "legacyfact1",
                            "text": "legacy fact about tea api_key=supersecretvalue123",
                            "source_session": "old",
                            "created_at": "2020-01-01T00:00:00",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (folder / "index.json").write_text(
            json.dumps(
                {
                    "conversations": [
                        {
                            "session_id": "old-chat",
                            "title": "Tea talk",
                            "summary": "talked about tea",
                            "updated_at": "2020-01-01T00:00:00",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with self._as("ada"):
            facts = list_facts()
            again = list_facts()
            brief = build_memory_brief()
            ada_blob = memory_db_path().read_bytes()
        self.assertEqual(len(facts), 1)
        self.assertEqual(len(again), 1)
        self.assertEqual(facts[0]["id"], "legacyfact1")
        self.assertNotIn("supersecretvalue123", facts[0]["text"])
        self.assertIn("Tea talk", brief)
        self.assertNotIn(b"supersecretvalue123", ada_blob)
        with self._as("bob"):
            self.assertEqual(list_facts(), [])
            self.assertNotIn(b"legacy fact", memory_db_path().read_bytes())

    def test_recall_escapes_like_wildcards(self) -> None:
        add_fact("the marker is idXrsa only")
        self.assertEqual(recall("id_rsa"), [])
        self.assertTrue(recall("idXrsa"))

    def test_slash_and_cli_list_and_delete(self) -> None:
        item = add_fact("Remembered fact about notebooks")
        self.assertIsNotNone(item)
        context = create_command_context(
            workspace_root=self.home,
            conversation=object(),
            cost_tracker=object(),
            history=object(),
        )
        success, result, error = execute_command_sync("memory", "list", context)
        self.assertTrue(success, error)
        self.assertIn(item["id"], result)
        self.assertIn("notebooks", result)
        success, recalled, error = execute_command_sync("memory", "recall notebooks", context)
        self.assertTrue(success, error)
        self.assertIn("notebooks", recalled)
        success, deleted, error = execute_command_sync("memory", f"delete {item['id']}", context)
        self.assertTrue(success, error)
        self.assertIn("Deleted", deleted)
        success, empty, error = execute_command_sync("memory", "", context)
        self.assertTrue(success, error)
        self.assertIn("No memories", empty)
        success, usage, error = execute_command_sync("memory", "explode", context)
        self.assertTrue(success, error)
        self.assertIn("Usage:", usage)

        from src.cli import main

        restored = add_fact("cli fact about kites")
        listed = io.StringIO()
        with patch.object(sys, "argv", ["clawd", "memory", "list"]), patch("sys.stdout", listed):
            code = main()
        self.assertEqual(code, 0)
        self.assertIn("kites", listed.getvalue())
        removed = io.StringIO()
        with (
            patch.object(sys, "argv", ["clawd", "memory", "delete", restored["id"]]),
            patch("sys.stdout", removed),
        ):
            code = main()
        self.assertEqual(code, 0)
        self.assertIn("Deleted", removed.getvalue())
        missing = io.StringIO()
        with (
            patch.object(sys, "argv", ["clawd", "memory", "delete", "missing-id"]),
            patch("sys.stdout", missing),
        ):
            code = main()
        self.assertEqual(code, 1)
        self.assertIn("No memory", missing.getvalue())


if __name__ == "__main__":
    unittest.main()
