"""Windows launcher probe order and in-place Setup folder discovery."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.install.app_root import (
    discover_existing_install,
    is_app_root,
    leftover_parent_exes,
    probe_app_roots,
)
from src.install.source import materialize_source
from src.install.windows_shortcuts import install_app_shortcuts, remove_parent_leftover_exes


def _make_app(root: Path, *, venv: bool = True, electron: bool = False) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "cli.py").write_text("# cli\n", encoding="utf-8")
    if venv:
        scripts = root / ".venv" / "Scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "python.exe").write_bytes(b"py")
    if electron:
        dist = root / "desktop" / "node_modules" / "electron" / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "electron.exe").write_bytes(b"el")
    return root


class TestAppRootProbe(unittest.TestCase):
    def test_parent_jonathan_folder_is_not_an_app_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            parent = home / "Jonathan"
            parent.mkdir()
            (parent / "JonathanAi.exe").write_bytes(b"MZ")
            app = _make_app(parent / "Jonathan-Ai")
            self.assertFalse(is_app_root(parent))
            self.assertTrue(is_app_root(app))
            found = probe_app_roots(exe_dir=parent, home=home, cwd=home)
            self.assertEqual(found, app.resolve())

    def test_probe_order_env_then_exe_then_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env_app = _make_app(home / "from-env")
            exe_app = _make_app(home / "from-exe")
            _make_app(home / "Jonathan" / "Jonathan-Ai")
            found = probe_app_roots(env_dir=env_app, exe_dir=exe_app, home=home, cwd=home)
            self.assertEqual(found, env_app.resolve())
            found = probe_app_roots(env_dir=home / "missing", exe_dir=exe_app, home=home, cwd=home)
            self.assertEqual(found, exe_app.resolve())

    def test_incomplete_env_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            empty = home / "empty"
            empty.mkdir()
            app = _make_app(home / "Jonathan" / "Jonathan-Ai")
            found = probe_app_roots(env_dir=empty, exe_dir=home / "Jonathan", home=home, cwd=home)
            self.assertEqual(found, app.resolve())

    def test_venv_without_electron_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _make_app(Path(tmp) / "Jonathan-Ai", venv=True, electron=False)
            self.assertTrue(is_app_root(app))

    def test_discover_reuses_clawd_code_and_prefers_jonathan_ai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(discover_existing_install(home=home), home / "Jonathan" / "Jonathan-Ai")
            clawd = _make_app(home / "Jonathan" / "Clawd-Code")
            self.assertEqual(discover_existing_install(home=home), clawd)
            jonathan = _make_app(home / "Jonathan" / "Jonathan-Ai")
            self.assertEqual(discover_existing_install(home=home), jonathan)


class TestInPlaceUpgradeAndShortcuts(unittest.TestCase):
    def test_second_materialize_upgrades_same_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "checkout"
            dest = Path(tmp) / "Jonathan" / "Jonathan-Ai"
            (src / "src").mkdir(parents=True)
            (src / "src" / "cli.py").write_text("first\n", encoding="utf-8")
            first = materialize_source(dest, from_local=src)
            self.assertEqual(first, dest.resolve())
            (src / "src" / "cli.py").write_text("second\n", encoding="utf-8")
            again = materialize_source(dest, from_local=src)
            self.assertEqual(again, dest.resolve())
            self.assertEqual((dest / "src" / "cli.py").read_text(encoding="utf-8"), "second\n")
            self.assertFalse((Path(tmp) / "Jonathan" / "Jonathan-Ai-2").exists())

    def test_upgrades_previous_clawd_code_and_forces_godesk_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "Jonathan" / "Clawd-Code"
            dest.mkdir(parents=True)
            (dest / "src").mkdir()
            (dest / "src" / "cli.py").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://github.com/GPT-AGI/Clawd-Code.git"],
                cwd=dest,
                check=True,
                capture_output=True,
            )
            src = Path(tmp) / "checkout"
            (src / "src").mkdir(parents=True)
            (src / "src" / "cli.py").write_text("godesk\n", encoding="utf-8")
            again = materialize_source(dest, from_local=src)
            self.assertEqual(again, dest.resolve())
            self.assertEqual((dest / "src" / "cli.py").read_text(encoding="utf-8"), "godesk\n")
            remotes = subprocess.run(
                ["git", "remote", "-v"], cwd=dest, check=True, capture_output=True, text=True
            )
            self.assertIn("GoDeskio/Clawd-Code", remotes.stdout)
            self.assertNotIn("GPT-AGI", remotes.stdout)

    def test_shortcuts_target_app_folder_and_remove_parent_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            parent = home / "Jonathan"
            app = parent / "Jonathan-Ai"
            app.mkdir(parents=True)
            leftover = parent / "JonathanAi.exe"
            leftover.write_bytes(b"old")
            bundled = Path(tmp) / "bundled.exe"
            bundled.write_bytes(b"new")
            desktop = home / "Desktop"
            start = home / "Start"
            with patch.dict("os.environ", {
                "CLAWD_DESKTOP_DIR": str(desktop),
                "CLAWD_START_MENU_DIR": str(start),
            }):
                result = install_app_shortcuts(app, bundled_exe=bundled)
            self.assertTrue((app / "JonathanAi.exe").exists())
            self.assertEqual((app / "JonathanAi.exe").read_bytes(), b"new")
            self.assertFalse(leftover.exists())
            self.assertEqual(result["target"], str(app / "JonathanAi.exe"))
            self.assertEqual(result["workdir"], str(app))
            self.assertNotIn(str(parent / "JonathanAi.exe"), Path(result["desktop"]).read_text(encoding="utf-8"))
            self.assertIn("Jonathan-Ai", Path(result["desktop"]).read_text(encoding="utf-8"))
            self.assertEqual(leftover_parent_exes(app)[0], parent / "JonathanAi.exe")
            remove_parent_leftover_exes(app)


if __name__ == "__main__":
    unittest.main()
