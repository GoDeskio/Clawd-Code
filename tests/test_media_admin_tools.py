from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from src.tool_system.audit import read_actions, record_action
from src.tool_system.context import ToolContext
from src.tool_system.tools.artifact import ArtifactTool
from src.tool_system.tools.image_studio import ImageStudioTool
from src.tool_system.tools.vision_analyze import VisionAnalyzeTool
from src.tool_system.tools.repository import RepositoryTool
from src.tool_system.tools.shared_memory import SharedMemoryTool
from src.tool_system.tools.skill_manager import SkillManagerTool
from src.tool_system.tools.system_admin import SystemAdminTool
from src.tool_system.tools.three_d_studio import ThreeDStudioTool, media_capabilities


class MediaAdminToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.workspace = self.root / "workspace"
        self.home.mkdir()
        self.workspace.mkdir()
        self.home_patch = patch("pathlib.Path.home", return_value=self.home)
        self.home_patch.start()
        self.context = ToolContext(workspace_root=self.workspace)
        self.context.artifact_publisher = lambda path, name=None: {
            "name": name or Path(path).name,
            "download_url": f"/api/artifacts/download?name={name or Path(path).name}",
            "size": Path(path).stat().st_size if Path(path).is_file() else 0,
        }

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.tmp.cleanup()

    def test_image_create_text_remove_and_convert(self) -> None:
        tool = ImageStudioTool()
        created = tool.run({"action": "create", "output": "media/base.png", "width": 320, "height": 180,
                            "background": "#14213d", "gradient_to": "#fca311"}, self.context)
        self.assertFalse(created.is_error)
        self.assertEqual((created.output["width"], created.output["height"]), (320, 180))
        text = tool.run({"action": "add_text", "source": "media/base.png", "output": "media/text.png",
                         "text": "Jonathan Ai", "font_size": 32, "x": 25, "y": 60, "color": "white"}, self.context)
        self.assertTrue(Path(text.output["path"]).is_file())
        removed = tool.run({"action": "remove_text", "source": "media/text.png", "output": "media/restored.png",
                            "regions": [{"x": 20, "y": 50, "width": 220, "height": 60}]}, self.context)
        self.assertTrue(Path(removed.output["path"]).is_file())
        converted = tool.run({"action": "convert", "source": "media/restored.png", "output": "media/final.webp"}, self.context)
        self.assertEqual(Image.open(converted.output["path"]).format, "WEBP")
        self.assertTrue(converted.output["artifacts"])

    def test_local_vision_reads_colors_shapes_and_dimensions(self) -> None:
        source = self.workspace / "vision.png"
        image = Image.new("RGB", (240, 160), "navy")
        from PIL import ImageDraw

        draw = ImageDraw.Draw(image)
        draw.rectangle((35, 35, 125, 125), fill="red")
        draw.ellipse((150, 45, 220, 115), fill="white")
        image.save(source)
        result = VisionAnalyzeTool().run({"source": str(source), "ocr": False}, self.context)
        self.assertEqual((result.output["width"], result.output["height"]), (240, 160))
        names = {row["name"] for row in result.output["dominant_colors"]}
        self.assertIn("navy", names)
        self.assertTrue(result.output["shapes"])
        self.assertIn("summary", result.output)

    def test_image_generation_defaults_to_local_even_with_stale_cloud_key(self) -> None:
        local_output = self.workspace / "fooocus-result.png"
        Image.new("RGB", (64, 40), "navy").save(local_output)
        manager = MagicMock()
        manager.generate.return_value = {
            "ok": True,
            "outputs": [{"path": str(local_output), "name": local_output.name, "size": local_output.stat().st_size}],
        }
        with patch(
            "src.tool_system.tools.image_studio.get_provider_config",
            return_value={"api_key": "stale-cloud-key", "base_url": "https://api.openai.com/v1"},
        ), patch("src.integrations.fooocus.FooocusManager", return_value=manager), patch(
            "src.tool_system.tools.image_studio.urllib.request.urlopen"
        ) as cloud_request:
            result = ImageStudioTool().run({
                "action": "generate",
                "prompt": "A blue mech",
                "output": "media/generated.png",
                "width": 64,
                "height": 40,
            }, self.context)

        self.assertEqual(result.output["engine"], "jonathan-local-diffusion")
        self.assertTrue(Path(result.output["path"]).is_file())
        manager.generate.assert_called_once()
        cloud_request.assert_not_called()

    def test_cloud_unauthorized_falls_back_to_local_fooocus(self) -> None:
        local_output = self.workspace / "fallback.png"
        Image.new("RGB", (48, 48), "gold").save(local_output)
        manager = MagicMock()
        manager.generate.return_value = {
            "ok": True,
            "outputs": [{"path": str(local_output), "name": local_output.name, "size": local_output.stat().st_size}],
        }
        unauthorized = urllib.error.HTTPError(
            "https://api.openai.com/v1/images/generations", 401, "Unauthorized", {}, None
        )
        with patch(
            "src.tool_system.tools.image_studio.get_provider_config",
            return_value={"api_key": "invalid", "base_url": "https://api.openai.com/v1"},
        ), patch("src.integrations.fooocus.FooocusManager", return_value=manager), patch(
            "src.tool_system.tools.image_studio.urllib.request.urlopen", side_effect=unauthorized
        ):
            result = ImageStudioTool().run({
                "action": "generate",
                "engine": "cloud",
                "prompt": "A gold mech",
                "output": "media/fallback-result.png",
                "width": 48,
                "height": 48,
            }, self.context)

        self.assertEqual(result.output["engine"], "jonathan-local-diffusion")
        self.assertIn("HTTP 401", result.output["warning"])
        manager.generate.assert_called_once()

    def test_ai_edit_defaults_to_local_fooocus_with_uploaded_source(self) -> None:
        source = self.workspace / "uploaded.png"
        generated = self.workspace / "variation.png"
        Image.new("RGB", (40, 30), "purple").save(source)
        Image.new("RGB", (40, 30), "blue").save(generated)
        manager = MagicMock()
        manager.generate.return_value = {
            "ok": True,
            "outputs": [{"path": str(generated), "name": generated.name, "size": generated.stat().st_size}],
        }
        with patch("src.integrations.fooocus.FooocusManager", return_value=manager), patch(
            "src.tool_system.tools.image_studio.get_provider_config", return_value={"api_key": "stale"}
        ):
            result = ImageStudioTool().run({
                "action": "ai_edit",
                "source": str(source),
                "prompt": "Keep the subject and add a blue cinematic background",
                "output": "media/edited.png",
                "width": 40,
                "height": 30,
            }, self.context)

        self.assertEqual(result.output["engine"], "jonathan-local-diffusion")
        self.assertTrue(Path(result.output["path"]).is_file())
        self.assertEqual(manager.generate.call_args.kwargs["source_image"], source)

    def test_3d_fallback_exports_colored_glb_and_mlb_alias(self) -> None:
        result = ThreeDStudioTool().run({
            "action": "create", "output": "media/robot.mlb",
            "objects": [{"type": "cube", "size": 2, "color": [30, 120, 255, 255]},
                        {"type": "sphere", "radius": .6, "translate": [0, 0, 1.5], "color": [255, 90, 30, 255]}],
        }, self.context)
        self.assertEqual(result.output["format"], "glb")
        self.assertIn("Corrected", result.output["note"])
        self.assertGreater(Path(result.output["path"]).stat().st_size, 100)
        capabilities = media_capabilities()
        self.assertTrue(capabilities["image"]["pillow"])
        self.assertTrue(capabilities["three_d"]["trimesh"])

    def test_artifact_accepts_any_file(self) -> None:
        source = self.workspace / "deliverable.custom"
        source.write_bytes(b"custom payload")
        result = ArtifactTool().run({"path": str(source), "name": "answer.custom"}, self.context)
        self.assertEqual(result.output["artifact"]["name"], "answer.custom")

    def test_system_snapshot_evaluation_and_report(self) -> None:
        tool = SystemAdminTool()
        snapshot = tool.run({"action": "evaluate", "process_limit": 3}, self.context)
        self.assertIn("evaluation", snapshot.output)
        self.assertLessEqual(len(snapshot.output["top_processes"]), 3)
        report = tool.run({"action": "report", "output": "admin/report.md", "format": "markdown"}, self.context)
        self.assertIn("System Report", Path(report.output["path"]).read_text(encoding="utf-8"))
        self.assertTrue(report.output["artifacts"])

    def test_skill_authoring_validation_and_packaging(self) -> None:
        tool = SkillManagerTool()
        created = tool.run({"action": "create", "name": "server-health", "scope": "project",
                            "description": "Inspect server health", "instructions": "Run SystemAdmin evaluate and report findings.",
                            "allowed_tools": ["SystemAdmin"]}, self.context)
        self.assertTrue(created.output["valid"])
        validated = tool.run({"action": "validate", "name": "server-health", "scope": "project"}, self.context)
        self.assertTrue(validated.output["valid"])
        packaged = tool.run({"action": "package", "name": "server-health", "scope": "project"}, self.context)
        self.assertTrue(packaged.output["artifact"]["name"].endswith(".zip"))

    def test_shared_memory_search_and_export(self) -> None:
        tool = SharedMemoryTool()
        tool.run({"action": "remember", "text": "Production server is named atlas"}, self.context)
        found = tool.run({"action": "search", "query": "atlas"}, self.context)
        self.assertEqual(len(found.output["facts"]), 1)
        exported = tool.run({"action": "export", "output": "memory/export.json"}, self.context)
        self.assertTrue(json.loads(Path(exported.output["path"]).read_text(encoding="utf-8"))["facts"])

    def test_repository_status_without_shell_interpolation(self) -> None:
        subprocess.run(["git", "init", "-b", "feature-test"], cwd=self.workspace, check=True, capture_output=True)
        result = RepositoryTool().run({"action": "status", "path": str(self.workspace)}, self.context)
        self.assertEqual(result.output["branch"], "feature-test")
        with self.assertRaises(Exception):
            RepositoryTool().run({"action": "push", "path": str(self.workspace), "branch": "main"}, self.context)

    def test_audit_log_is_utf8_and_redacts_secrets(self) -> None:
        record_action({"tool": "Example", "session_id": "abc", "input": {"api_key": "secret", "text": "héllo"}, "status": "success"})
        rows = read_actions(10, tool="Example")
        self.assertEqual(rows[0]["input"]["api_key"], "[redacted]")
        self.assertEqual(rows[0]["input"]["text"], "héllo")


if __name__ == "__main__":
    unittest.main()
