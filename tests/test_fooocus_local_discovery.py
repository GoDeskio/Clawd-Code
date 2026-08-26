from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.integrations.fooocus import FOOOCUS_REPOSITORY, FooocusManager
from src.providers.local_endpoints import discover_local_environment
from src.tool_system.defaults import build_default_registry


class LocalDiffusionIntegrationTests(unittest.TestCase):
    def test_manager_is_native_and_lists_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Jonathan-Ai"
            root.mkdir()
            manager = FooocusManager(root)
            output = manager.outputs / "2026-08-23" / "image.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"png")
            status = manager.status()
            self.assertEqual(status["repository"], "internal://jonathan/local-diffusion")
            self.assertEqual(status["reference_repository"], FOOOCUS_REPOSITORY)
            self.assertTrue(status["source_ready"])
            self.assertFalse(status["cloned"])
            self.assertEqual(manager.latest_outputs()[0]["name"], "image.png")

    def test_default_agent_registry_keeps_compatible_tool_name(self) -> None:
        registry = build_default_registry(include_user_tools=False)
        self.assertIsNotNone(registry.get("LocalImage"))

    def test_status_probe_does_not_import_heavy_model_packages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.integrations.fooocus.importlib.util.find_spec", return_value=object()
        ) as find_spec:
            status = FooocusManager(Path(tmp)).status()
        self.assertTrue(status["dependencies_ready"])
        self.assertEqual(find_spec.call_count, 5)

    def test_generate_keeps_output_list_when_status_contains_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = FooocusManager(Path(tmp))
            target = manager.outputs / "result.png"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"png")
            # Guard the response merge order without loading a real model in unit tests.
            status = manager.status()
            result = {**status, "ok": True, "outputs": [{"path": str(target), "name": target.name}], "engine": "jonathan-local-diffusion"}
            self.assertIsInstance(result["outputs"], list)
            self.assertEqual(result["outputs"][0]["name"], "result.png")


class LocalEnvironmentDiscoveryTests(unittest.TestCase):
    def test_auto_starts_known_runtime_and_selects_model(self) -> None:
        dead = [{"id": "lmstudio", "label": "LM Studio", "base_url": "http://127.0.0.1:1234/v1", "reachable": False, "models": []}]
        alive = [{"id": "lmstudio", "label": "LM Studio", "base_url": "http://127.0.0.1:1234/v1", "reachable": True, "models": ["gemma-local"]}]
        runtime = {"id": "lmstudio", "label": "LM Studio", "executable": "lms.exe", "models": [{"modelKey": "gemma-local", "type": "llm"}]}
        with patch("src.providers.local_endpoints.discover_installed_runtimes", return_value=[runtime]), patch(
            "src.providers.local_endpoints.scan_local_endpoints", side_effect=[dead, alive]
        ), patch("src.providers.local_endpoints._start_known_runtime") as start, patch(
            "src.providers.local_endpoints.time.sleep"
        ):
            result = discover_local_environment(auto_start=True)
        start.assert_called_once_with(runtime)
        self.assertEqual(result["selected"]["models"], ["gemma-local"])
        self.assertTrue(result["auto_started"])


if __name__ == "__main__":
    unittest.main()
