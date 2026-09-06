from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.skills.learning import record_observation, review_observations


class SkillObservationReviewTests(unittest.TestCase):
    def test_corrections_are_clustered_but_never_activated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            root.mkdir(); home.mkdir()
            events = [{"type": "tool_result", "tool_name": name} for name in ("Read", "Edit", "Bash")]
            with patch("src.skills.learning.Path.home", return_value=home):
                first = record_observation(root, session_id="a", request="This is still wrong; fix it instead.", response="fixed", tool_events=events)
                record_observation(root, session_id="b", request="You missed the required test.", response="tested", tool_events=events)
                review = review_observations(root)
        self.assertIn("user-correction", first["signals"])
        self.assertTrue(first["review_candidate"])
        self.assertEqual(review["candidates"][0]["recommendation"], "review-for-skill-draft")
        self.assertFalse(review["automatic_activation"])
