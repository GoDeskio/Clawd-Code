from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.event_log import append_runtime_event, read_runtime_events


class RuntimeEventLogTests(unittest.TestCase):
    def test_events_are_utf8_redacted_and_hash_chained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("src.agent.event_log.event_log_dir", return_value=Path(tmp)):
            append_runtime_event("session-1", "job_started", {"text": "hello ✓", "api_key": "do-not-store"}, job_id="job-1")
            append_runtime_event("session-1", "done", {"usage": {"input_tokens": 4, "output_tokens": 2}}, job_id="job-1")
            result = read_runtime_events("session-1")
        self.assertTrue(result["valid_chain"])
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["events"][0]["payload"]["api_key"], "[redacted]")
        self.assertEqual(result["events"][1]["previous_hash"], result["events"][0]["event_hash"])

    def test_tampering_is_detected_without_hiding_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("src.agent.event_log.event_log_dir", return_value=Path(tmp)):
            append_runtime_event("session-2", "done", {"text": "original"})
            target = Path(tmp) / "session-2.jsonl"
            row = json.loads(target.read_text(encoding="utf-8"))
            row["payload"]["text"] = "changed"
            target.write_text(json.dumps(row) + "\n", encoding="utf-8")
            result = read_runtime_events("session-2")
        self.assertFalse(result["valid_chain"])
        self.assertEqual(result["events"][0]["payload"]["text"], "changed")

