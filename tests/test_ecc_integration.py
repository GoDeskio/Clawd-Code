from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.integrations.ecc import (
    catalog,
    ecc_cache_dir,
    import_catalog,
    security_scan,
    set_enabled,
)
from src.skills.learning import analyze_git_history, record_observation
from src.skills.loader import clear_skill_registry, get_all_skills


def _skill(name: str, description: str = "Use when testing the managed ECC catalog.") -> str:
    return f'---\nname: "{name}"\ndescription: "{description}"\n---\n\n# {name}\n\nRun the focused test.\n'


class ECCIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.skills = self.root / "Skills"
        cache = ecc_cache_dir(self.root)
        (cache / "skills" / "safe-workflow").mkdir(parents=True)
        (cache / "skills" / "safe-workflow" / "SKILL.md").write_text(_skill("safe-workflow"), encoding="utf-8")
        (cache / "agents").mkdir(parents=True)
        (cache / "agents" / "reviewer.md").write_text(
            '---\nname: "reviewer"\ndescription: "Review completed work."\n---\n\nCheck evidence.\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        clear_skill_registry()
        self.tmp.cleanup()

    def test_catalog_imports_everything_but_loads_only_enabled_skills(self) -> None:
        with patch.dict(os.environ, {"CLAWD_SKILLS_DIR": str(self.skills)}):
            available = catalog(self.root)
            result = import_catalog(self.root, enable_names=[])
            unloaded = {item.name for item in get_all_skills(project_root=self.root)}
            set_enabled(["safe-workflow"], True, self.root)
            loaded = {item.name for item in get_all_skills(project_root=self.root)}
        self.assertEqual(available["counts"]["skills"], 1)
        self.assertEqual(result["imported_skills"], ["safe-workflow"])
        self.assertNotIn("safe-workflow", unloaded)
        self.assertIn("safe-workflow", loaded)

    def test_security_scan_flags_embedded_credentials(self) -> None:
        path = self.root / "unsafe"
        path.mkdir()
        (path / "SKILL.md").write_text("token ghp_abcdefghijklmnopqrstuvwxyz123456", encoding="utf-8")
        result = security_scan(path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["critical"], 1)

    def test_observations_are_redacted_and_do_not_activate_skills(self) -> None:
        with patch("src.skills.learning.learning_root", return_value=self.root / "learning"):
            item = record_observation(
                self.root,
                session_id="session-1",
                request="Use api_key=top-secret-value and finish the task",
                response="Done",
                successful=True,
            )
        self.assertIn("[redacted]", item["request"])
        self.assertFalse((self.skills / "SKILL.md").exists())


class GitLearningTests(unittest.TestCase):
    def test_git_history_generates_a_valid_reviewable_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "jonathan@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Jonathan Test"], cwd=root, check=True)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_value(): assert True\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "feat: add application"], cwd=root, check=True, capture_output=True)
            with patch("src.skills.learning.learning_root", return_value=root / ".learning"):
                result = analyze_git_history(root, 20)
            self.assertTrue(result["validation"]["valid"])
            self.assertIn("source: local-git-analysis", result["content"])
            self.assertIn("tests/test_app.py", result["content"])
            self.assertTrue(Path(result["draft_path"]).is_file())
            self.assertGreater(result["confidence"], 0)


if __name__ == "__main__":
    unittest.main()
