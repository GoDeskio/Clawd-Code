from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.errors import ToolInputError
from src.tool_system.tools.self_hosted_service import SelfHostedServiceTool


class SelfHostedServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = self.root / "services.json"
        self.env = patch.dict(os.environ, {"JONATHAN_SERVICE_STORE": str(self.store)})
        self.env.start()
        self.context = ToolContext(workspace_root=self.root)
        self.context.artifact_publisher = lambda path, name=None: {"name": name or Path(path).name, "path": str(path)}
        self.tool = SelfHostedServiceTool()
        self.project = self.root / "stack"
        self.project.mkdir()
        (self.project / "compose.yaml").write_text("services:\n  app:\n    image: example/app:1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.env.stop()
        self.temporary.cleanup()

    def register(self) -> dict:
        return self.tool.run({
            "action": "register", "name": "Café service", "driver": "docker_compose",
            "project_dir": str(self.project), "compose_file": "compose.yaml", "backup_paths": ["data"],
            "health_url": "http://127.0.0.1:8080/health",
        }, self.context).output["service"]

    def test_registered_and_utf8_persistent(self) -> None:
        self.assertIsNotNone(build_default_registry(include_user_tools=False).get("SelfHostedService"))
        service = self.register()
        listed = self.tool.run({"action": "list"}, self.context).output
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["services"][0]["id"], service["id"])
        self.assertIn("Café service", self.store.read_text(encoding="utf-8"))

    def test_compose_status_uses_fixed_arguments_without_shell(self) -> None:
        service = self.register()
        completed = subprocess.CompletedProcess([], 0, stdout='{"Name":"app","State":"running"}\n', stderr="")
        with patch("src.tool_system.tools.self_hosted_service.shutil.which", return_value="docker"), patch(
            "src.tool_system.tools.self_hosted_service.subprocess.run", return_value=completed
        ) as run, patch("src.tool_system.tools.self_hosted_service._health", return_value={"reachable": True, "status": 200}):
            result = self.tool.run({"action": "status", "service_id": service["id"]}, self.context).output
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["docker", "compose"])
        self.assertEqual(command[-3:], ["ps", "--format", "json"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(result["health"]["status"], 200)

    def test_backup_is_downloadable_and_bounded(self) -> None:
        service = self.register()
        data = self.project / "data"
        data.mkdir()
        (data / "state.txt").write_text("healthy", encoding="utf-8")
        with self.assertRaises(ToolInputError):
            self.tool.run({"action": "update", "service_id": service["id"]}, self.context)
        result = self.tool.run({
            "action": "backup", "service_id": service["id"], "output": "backups/service.zip",
        }, self.context).output
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertIn("data/state.txt", archive.namelist())
        self.assertEqual(result["artifacts"][0]["name"], "service.zip")
        inspected = self.tool.run({"action": "inspect", "service_id": service["id"]}, self.context).output
        self.assertEqual(inspected["last_backup"]["files"], 1)

    def test_remove_archives_instead_of_erasing(self) -> None:
        service = self.register()
        removed = self.tool.run({"action": "remove", "service_id": service["id"]}, self.context).output
        self.assertTrue(removed["recoverable"])
        self.assertEqual(self.tool.run({"action": "list"}, self.context).output["count"], 0)
        self.assertEqual(self.tool.run({"action": "list", "include_archived": True}, self.context).output["count"], 1)


if __name__ == "__main__":
    unittest.main()
