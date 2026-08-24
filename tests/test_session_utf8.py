"""Session JSON must be read/written as UTF-8 on Windows (not cp1252)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.session import Session


# U+020F encodes as C8 8F. Byte 0x8F is undefined in Windows-1252 (cp1252).
_CP1252_UNSAFE = "hello \u020f"


class TestSessionUtf8(unittest.TestCase):
    def test_load_utf8_byte_that_fails_cp1252(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            sessions = home / ".clawd" / "sessions"
            sessions.mkdir(parents=True)
            session_id = "sess_cp1252_8f"
            payload = {
                "session_id": session_id,
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "conversation": {
                    "messages": [
                        {"role": "user", "content": _CP1252_UNSAFE, "timestamp": ""},
                    ],
                    "max_history": 100,
                },
                "created_at": "2026-08-23T00:00:00",
                "updated_at": "2026-08-23T00:00:00",
                "workspace": "",
                "title": _CP1252_UNSAFE,
                "custom_title": True,
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            }
            raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
            self.assertIn(0x8F, raw)
            path = sessions / f"{session_id}.json"
            path.write_bytes(raw)

            with self.assertRaises(UnicodeDecodeError):
                path.read_text(encoding="cp1252")

            with patch("src.agent.session.Path.home", return_value=home):
                loaded = Session.load(session_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.title, _CP1252_UNSAFE)
            self.assertEqual(loaded.conversation.messages[0].content, _CP1252_UNSAFE)

    def test_save_writes_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with patch("src.agent.session.Path.home", return_value=home):
                session = Session.create("anthropic", "claude-sonnet-4-6")
                session.conversation.add_message("user", _CP1252_UNSAFE)
                session.rename(_CP1252_UNSAFE)
                path = home / ".clawd" / "sessions" / f"{session.session_id}.json"
                raw = path.read_bytes()
                self.assertIn(0x8F, raw)
                with self.assertRaises(UnicodeDecodeError):
                    path.read_text(encoding="cp1252")
                loaded = Session.load(session.session_id)
                self.assertEqual(loaded.title, _CP1252_UNSAFE)


if __name__ == "__main__":
    unittest.main()
