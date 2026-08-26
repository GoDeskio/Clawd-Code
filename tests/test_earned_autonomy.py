from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.autonomy import autonomy_status, record_permission_evidence, wilson_lower_bound


class EarnedAutonomyTests(unittest.TestCase):
    def test_wilson_bound_penalizes_small_samples(self) -> None:
        self.assertLess(wilson_lower_bound(3, 3), 0.5)
        self.assertGreater(wilson_lower_bound(40, 40), 0.9)

    def test_decisions_are_utf8_persistent_and_replay_resistant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "evidence.json"
            with patch("src.agent.autonomy.autonomy_store_path", return_value=target):
                record_permission_evidence("agent-✓", "websearch", "allow", "decision-1")
                record_permission_evidence("agent-✓", "websearch", "allow", "decision-1")
                result = autonomy_status("agent-✓")
                self.assertEqual(result["profiles"][0]["total_decisions"], 1)
                self.assertIn("agent-✓", target.read_text(encoding="utf-8"))

    def test_high_risk_actions_never_recommend_beyond_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "evidence.json"
            with patch("src.agent.autonomy.autonomy_store_path", return_value=target):
                for index in range(50):
                    record_permission_evidence("agent", "powershell", "allow", f"decision-{index}")
                profile = autonomy_status("agent")["profiles"][0]
                self.assertEqual(profile["autonomy_ceiling"], 3)
                self.assertEqual(profile["recommended_level"], 3)
                self.assertEqual(profile["enforced_level"], 3)

    def test_recommendations_do_not_change_enforced_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "evidence.json"
            with patch("src.agent.autonomy.autonomy_store_path", return_value=target):
                for index in range(40):
                    record_permission_evidence("agent", "read", "allow", f"decision-{index}")
                profile = autonomy_status("agent")["profiles"][0]
                self.assertGreater(profile["recommended_level"], profile["enforced_level"])
                self.assertEqual(autonomy_status("agent")["mode"], "recommendation_only")


if __name__ == "__main__":
    unittest.main()
