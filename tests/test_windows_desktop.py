"""Windows installer artifacts, shortcuts, and branded desktop UI."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.install.win_gui import WIZARD_BUTTONS, WIZARD_PAGES, robot_image_path
from src.install.windows_shortcuts import create_windows_shortcuts, find_app_executable


ROOT = Path(__file__).resolve().parents[1]


class TestWindowsArtifacts(unittest.TestCase):
    def test_setup_and_app_exes_are_pe(self) -> None:
        setup = ROOT / "packaging" / "windows" / "bin" / "JonathanAi-Setup.exe"
        app = ROOT / "packaging" / "windows" / "bin" / "JonathanAi.exe"
        self.assertTrue(setup.exists(), "JonathanAi-Setup.exe must be shipped")
        self.assertTrue(app.exists(), "JonathanAi.exe must be shipped")
        self.assertTrue(setup.read_bytes().startswith(b"MZ"))
        self.assertTrue(app.read_bytes().startswith(b"MZ"))

    def test_robot_branding_files(self) -> None:
        self.assertTrue((ROOT / "src" / "desktop" / "web" / "robot.png").exists())
        self.assertTrue((ROOT / "src" / "desktop" / "web" / "favicon.ico").exists())
        self.assertTrue((ROOT / "packaging" / "windows" / "jonathan-ai.ico").exists())
        self.assertTrue(robot_image_path().exists())

    def test_wizard_copy_has_next_install_finish(self) -> None:
        self.assertEqual(WIZARD_PAGES[0], "Welcome")
        self.assertIn("Install", WIZARD_BUTTONS)
        self.assertIn("Finish", WIZARD_BUTTONS)
        self.assertIn("Next", WIZARD_BUTTONS)
        source = (ROOT / "src" / "install" / "win_gui.py").read_text(encoding="utf-8")
        self.assertIn("Launch", source)
        setup_c = (ROOT / "packaging" / "windows" / "JonathanAi-Setup.c").read_text(encoding="utf-8")
        self.assertIn("Next", setup_c)
        self.assertIn("Install", setup_c)
        self.assertIn("Finish", setup_c)
        self.assertIn("Jonathan Ai.lnk", setup_c)
        self.assertIn("Jonathan\\\\Jonathan-Ai", setup_c)
        self.assertIn("upgrade in place", setup_c.lower())
        self.assertIn("Clawd-Code", setup_c)
        self.assertNotIn("merge --ff-only origin/main", setup_c)
        self.assertIn("main is not merged", setup_c)
        self.assertIn("CopyFileW", setup_c)
        launcher = (ROOT / "packaging" / "windows" / "JonathanAi.c").read_text(encoding="utf-8")
        self.assertIn("CLAWD_SOURCE_DIR", launcher)
        self.assertIn("Jonathan\\\\Jonathan-Ai", launcher)
        self.assertIn("pythonw.exe", launcher)
        self.assertIn("-m src.cli desktop", launcher)
        self.assertIn("is_app_root", launcher)
        self.assertIn("src\\\\cli.py", launcher)
        self.assertIn("src.install.bootstrap", launcher)
        self.assertIn("run_bootstrap", launcher)


class TestShortcuts(unittest.TestCase):
    def test_creates_desktop_and_start_menu_links(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            home_desktop = Path(tmp) / "Desktop"
            start = Path(tmp) / "Start"
            target = Path(tmp) / "JonathanAi.exe"
            target.write_bytes(b"MZ")
            with patch.dict("os.environ", {
                "CLAWD_DESKTOP_DIR": str(home_desktop),
                "CLAWD_START_MENU_DIR": str(start),
            }):
                result = create_windows_shortcuts(target)
            self.assertTrue(Path(result["desktop"]).exists())
            self.assertTrue(Path(result["start_menu"]).exists())
            self.assertEqual(result["name"], "Jonathan Ai")
            self.assertIn("Jonathan Ai", Path(result["desktop"]).read_text(encoding="utf-8"))

    def test_finds_packaged_exe(self) -> None:
        exe = find_app_executable(ROOT)
        self.assertTrue(str(exe).endswith("JonathanAi.exe"))


class TestDashboardHtml(unittest.TestCase):
    def test_glass_dashboard_and_conversation_list(self) -> None:
        html = (ROOT / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "src" / "desktop" / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("robot.png", html)
        self.assertIn("Conversations", html)
        self.assertIn("0.2.7", html)
        self.assertIn("session-menu", html)
        self.assertIn("standalone", html)
        self.assertIn("informational", html)
        self.assertIn("backdrop-filter", css)
        self.assertIn("glass", css)
        self.assertNotIn("Buy tokens", html)
        self.assertNotIn("out of tokens", html)


if __name__ == "__main__":
    unittest.main()
