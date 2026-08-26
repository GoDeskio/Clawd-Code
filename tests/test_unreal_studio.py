from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.tools.unreal_studio import UnrealStudioTool


class TestUnrealStudio(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertIsNotNone(build_default_registry(include_user_tools=False).get("UnrealStudio"))

    def test_status_and_project_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "Demo.uproject"
            project.write_text(json.dumps({"EngineAssociation": "5.6", "Modules": [{"Name": "Demo"}]}), encoding="utf-8")
            result = UnrealStudioTool().run({"action": "status"}, ToolContext(workspace_root=root))
            self.assertIn(str(project), result.output["projects"])
            detail = UnrealStudioTool().run({"action": "inspect_project", "project": str(project)}, ToolContext(workspace_root=root))
            self.assertEqual(detail.output["engine_association"], "5.6")

    def test_generates_reviewable_scene_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "Saved" / "JonathanAi" / "scene.py"
            result = UnrealStudioTool().run({
                "action": "generate_scene_script", "output": str(output),
                "actors": [{"name": "Hero", "location": [1, 2, 3]}],
            }, ToolContext(workspace_root=root))
            self.assertTrue(result.output["created"])
            text = output.read_text(encoding="utf-8")
            self.assertIn("Hero", text)
            self.assertIn("EditorActorSubsystem", text)


if __name__ == "__main__":
    unittest.main()
