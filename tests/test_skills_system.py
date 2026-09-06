from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.skills.create import create_skill
from src.skills.frontmatter import parse_frontmatter
from src.skills.loader import clear_skill_registry, get_all_skills
from src.skills.library import render_skill, save_user_skill, validate_skill_source
from src.tool_system.context import ToolContext
from src.tool_system.tools import SkillManagerTool, SkillTool


class SkillSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        clear_skill_registry()
        self.tmp.cleanup()


class TestSkillCreate(SkillSystemTests):
    def test_create_writes_skill_md(self) -> None:
        skills_dir = self.root / "skills"
        p = create_skill(
            directory=skills_dir,
            name="demo",
            description="demo skill",
            when_to_use="use it when testing",
            allowed_tools=["Read", "Grep"],
            arguments=["foo", "bar"],
            body="Hello $foo $1",
        )
        self.assertTrue(p.exists())
        parsed = parse_frontmatter(p.read_text(encoding="utf-8"))
        self.assertEqual(parsed.frontmatter["description"], "demo skill")
        self.assertEqual(parsed.frontmatter["when_to_use"], "use it when testing")

    def test_parse_frontmatter_supports_inline_lists(self) -> None:
        parsed = parse_frontmatter(
            "---\n"
            "arguments: [name]\n"
            "allowed-tools: [Read, Grep]\n"
            "---\n"
            "Hello $name\n"
        )
        self.assertEqual(parsed.frontmatter["arguments"], ["name"])
        self.assertEqual(parsed.frontmatter["allowed-tools"], ["Read", "Grep"])

    def test_visible_library_round_trips_valid_utf8_skill(self) -> None:
        skills_dir = self.root / "Jonathan" / "Jonathan-Ai" / "Skills"
        source = render_skill(
            name="image-review",
            description="Inspect an uploaded image before editing it.",
            instructions="Use VisionAnalyze, then preserve the user's subject during edits.",
            allowed_tools=["VisionAnalyze", "ImageStudio"],
        )
        with patch.dict(os.environ, {"CLAWD_SKILLS_DIR": str(skills_dir)}):
            saved = save_user_skill("image-review", source)
            validation = validate_skill_source("image-review", saved["content"])
            skills = {skill.name: skill for skill in get_all_skills(project_root=self.root)}
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["description"], "Inspect an uploaded image before editing it.")
        self.assertIn("image-review", skills)
        self.assertEqual(skills["image-review"].loaded_from, "user")

    def test_skill_manager_defaults_agent_learning_to_visible_user_library(self) -> None:
        skills_dir = self.root / "visible-skills"
        with patch.dict(os.environ, {"CLAWD_SKILLS_DIR": str(skills_dir)}):
            result = SkillManagerTool().run({
                "action": "create",
                "name": "release-check",
                "description": "Verify a completed release.",
                "instructions": "Run the focused tests and verify packaged checksums.",
                "allowed_tools": ["Read", "Bash"],
            }, ToolContext(workspace_root=self.root))
        path = skills_dir / "release-check" / "SKILL.md"
        self.assertTrue(result.output["valid"])
        self.assertEqual(result.output["scope"], "user")
        self.assertTrue(path.is_file())
        self.assertEqual(parse_frontmatter(path.read_text(encoding="utf-8")).frontmatter["name"], "release-check")


class TestSkillRegister(SkillSystemTests):
    def test_register_loads_skill_from_dir(self) -> None:
        skills_dir = self.root / "skills"
        create_skill(
            directory=skills_dir,
            name="hello",
            description="say hello",
            body="Hello",
        )
        with patch.dict(os.environ, {"CLAWD_SKILLS_DIR": str(skills_dir)}):
            skills = get_all_skills(project_root=self.root)
            by_name = {s.name: s for s in skills}
            self.assertIn("hello", by_name)
            self.assertEqual(by_name["hello"].description, "say hello")
            self.assertEqual(by_name["hello"].loaded_from, "user")


class TestSkillUse(SkillSystemTests):
    def test_use_substitutes_arguments(self) -> None:
        skills_dir = self.root / "skills"
        create_skill(
            directory=skills_dir,
            name="hello",
            description="say hello",
            arguments=["name"],
            body="Hello $name ($0) / $ARGUMENTS",
        )
        ctx = ToolContext(workspace_root=self.root)
        with patch.dict(os.environ, {"CLAWD_SKILLS_DIR": str(skills_dir)}):
            out = SkillTool().run({"skill": "hello", "args": 'bob "the builder"'}, ctx).output
            self.assertTrue(out["success"])
            self.assertIn("Hello bob (bob)", out["prompt"])
            self.assertIn('bob "the builder"', out["prompt"])
