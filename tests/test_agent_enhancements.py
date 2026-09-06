from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.checkpoints import create_checkpoint, list_checkpoints, prepare_retry, restore_checkpoint, undo_last_turn
from src.agent.history_search import search_history
from src.agent.roster import list_agents, read_inbox, remove_agent, save_agent, send_message
from src.agent.session import Session
from src.skills.loader import get_all_skills


class AgentEnhancementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.temp.cleanup()

    def test_unbounded_history_does_not_drop_old_messages(self) -> None:
        session = Session.create("local", "model")
        for index in range(140):
            session.conversation.add_user_message(f"message {index}")
        self.assertEqual(len(session.conversation.messages), 140)
        session.save()
        loaded = Session.load(session.session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.conversation.messages), 140)
        self.assertEqual(loaded.conversation.max_history, 0)

    def test_history_search_indexes_messages_and_memory(self) -> None:
        session = Session.create("local", "model")
        session.conversation.add_user_message("Find the cobalt launch checklist")
        session.conversation.add_assistant_message("The checklist is ready.")
        session.save()
        result = search_history("cobalt checklist")
        self.assertTrue(result["fts5"])
        self.assertTrue(any(hit["session_id"] == session.session_id for hit in result["hits"]))

    def test_checkpoints_support_restore_undo_and_retry(self) -> None:
        session = Session.create("local", "model")
        session.conversation.add_user_message("first")
        session.conversation.add_assistant_message("answer")
        checkpoint = create_checkpoint(session)
        session.conversation.add_user_message("second")
        session.conversation.add_assistant_message("answer two")
        restored = restore_checkpoint(session, checkpoint["id"])
        self.assertEqual(len(restored["messages"]), 2)
        session.conversation.add_user_message("retry me")
        session.conversation.add_assistant_message("old answer")
        self.assertEqual(prepare_retry(session), "retry me")
        self.assertEqual(len(session.export_messages()), 2)
        session.conversation.add_user_message("undo me")
        session.conversation.add_tool_result_message("tool-1", {"ok": True})
        session.conversation.add_assistant_message("answer")
        undone = undo_last_turn(session)
        self.assertEqual(len(undone["messages"]), 2)
        self.assertGreaterEqual(len(list_checkpoints(session.session_id)), 3)

    def test_named_agent_roster_and_mailbox_are_persistent(self) -> None:
        agent = save_agent({"name": "Release Engineer", "instructions": "Own builds."}, canonical_session_id="session-1")
        message = send_message(sender_session_id="session-root", recipient_agent_id=agent["id"], text="Build version 1")
        self.assertEqual(list_agents()[0]["canonical_session_id"], "session-1")
        self.assertEqual(read_inbox(agent["id"])[0]["id"], message["id"])
        marked = read_inbox(agent["id"], mark_read=True)
        self.assertTrue(marked[0]["read_at"])
        self.assertTrue(remove_agent(agent["id"])["conversation_retained"])

    def test_all_bundled_skills_are_loadable(self) -> None:
        skills = get_all_skills(project_root=self.home)
        names = {skill.name for skill in skills if skill.loaded_from == "bundled"}
        self.assertGreaterEqual(len(names), 200)
        self.assertTrue(all(skill.markdown_content.strip() for skill in skills if skill.loaded_from == "bundled"))


if __name__ == "__main__":
    unittest.main()
