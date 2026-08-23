"""First-launch dependency bootstrap repairs venv/pip without failing Electron."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.install.bootstrap import ensure_runtime_deps, resolve_source


class TestBootstrap(unittest.TestCase):
    def test_resolve_source_prefers_folder_with_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Jonathan" / "Jonathan-Ai"
            (root / "src").mkdir(parents=True)
            (root / "src" / "cli.py").write_text("# cli\n", encoding="utf-8")
            self.assertEqual(resolve_source(root), root.resolve())

    def test_skips_pip_when_imports_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "app"
            (root / "src").mkdir(parents=True)
            (root / "src" / "cli.py").write_text("# cli\n", encoding="utf-8")
            python = Path(tmp) / "python"
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            with patch("src.install.bootstrap.ensure_venv", return_value=python), patch(
                "src.install.bootstrap.venv_is_usable", return_value=True
            ), patch(
                "src.install.bootstrap._imports_ok", return_value=True
            ), patch(
                "src.install.bootstrap.install_python_deps"
            ) as pip, patch(
                "src.install.bootstrap.install_desktop_deps", return_value="skipped"
            ), patch(
                "src.install.bootstrap.write_install_record"
            ):
                result = ensure_runtime_deps(root, skip_desktop=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["pip"], "ok")
            pip.assert_not_called()

    def test_installs_pip_when_imports_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "app"
            (root / "src").mkdir(parents=True)
            (root / "src" / "cli.py").write_text("# cli\n", encoding="utf-8")
            python = Path(tmp) / "python"
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            with patch("src.install.bootstrap.ensure_venv", return_value=python), patch(
                "src.install.bootstrap.venv_is_usable", return_value=True
            ), patch(
                "src.install.bootstrap._imports_ok", side_effect=[False, True]
            ), patch(
                "src.install.bootstrap.install_python_deps"
            ) as pip, patch(
                "src.install.bootstrap.install_desktop_deps", return_value="skipped"
            ), patch(
                "src.install.bootstrap.write_install_record"
            ):
                result = ensure_runtime_deps(root, skip_desktop=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["pip"], "installed")
            pip.assert_called_once()


if __name__ == "__main__":
    unittest.main()
