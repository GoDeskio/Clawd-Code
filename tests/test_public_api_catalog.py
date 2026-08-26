from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.connectors.store import read_connectors
from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.tools.public_api_catalog import PublicApiCatalogTool


class PublicApiCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.workspace = Path(self.tmp.name) / "workspace"
        self.home.mkdir(); self.workspace.mkdir()
        self.home_patch = patch("pathlib.Path.home", return_value=self.home)
        self.home_patch.start()
        self.context = ToolContext(workspace_root=self.workspace)
        self.context.gate_destructive_tools = True
        self.tool = PublicApiCatalogTool()

    def tearDown(self) -> None:
        self.home_patch.stop(); self.tmp.cleanup()

    def test_search_and_categories_are_offline_and_read_only(self) -> None:
        result = self.tool.run({"action": "search", "category": "Science"}, self.context).output
        self.assertTrue(result["offline_catalog"])
        self.assertGreaterEqual(result["count"], 2)
        self.assertEqual(self.tool.check_permissions({"action": "categories"}, self.context).behavior, PermissionBehavior.ALLOW)

    def test_connect_adds_a_persistent_connector_and_requires_permission(self) -> None:
        permission = self.tool.check_permissions({"action": "connect", "id": "open-meteo"}, self.context)
        self.assertEqual(permission.behavior, PermissionBehavior.ASK)
        result = self.tool.run({"action": "connect", "id": "open-meteo"}, self.context).output
        self.assertTrue(result["connected"])
        service = read_connectors()["services"][0]
        self.assertEqual(service["id"], "public-api-open-meteo")
        self.assertEqual(service["auth_type"], "none")

    def test_credentials_are_required_when_catalog_marks_api_key(self) -> None:
        with self.assertRaises(ToolInputError):
            self.tool.run({"action": "connect", "id": "nasa"}, self.context)


if __name__ == "__main__":
    unittest.main()
