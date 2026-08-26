"""Windows installer artifacts, shortcuts, and branded desktop UI."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.install.win_gui import WIZARD_BUTTONS, WIZARD_PAGES, robot_image_path
from src.install.windows_shortcuts import create_windows_shortcuts, find_app_executable, shortcut_script


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
        self.assertIn("runtime_ready", launcher)
        self.assertIn(".jonathan-ai-runtime-0.4.6.ready", launcher)
        self.assertIn("CLAWD_DESKTOP_MANAGED_BY_LAUNCHER", launcher)
        self.assertIn("start_process_checked", launcher)
        self.assertIn("code == STILL_ACTIVE", launcher)
        self.assertIn("QueryFullProcessImageNameW", setup_c)
        self.assertIn("_wcsnicmp(image, dest", setup_c)
        inno = (ROOT / "packaging" / "windows" / "JonathanAi.iss").read_text(encoding="utf-8")
        self.assertIn("DefaultDirName={userprofile}\\Jonathan\\Jonathan-Ai", inno)
        self.assertIn("$p.Path.StartsWith($root", inno)
        nsis = (ROOT / "packaging" / "windows" / "JonathanAi.nsi").read_text(encoding="utf-8")
        self.assertIn('InstallDir "$PROFILE\\Jonathan\\Jonathan-Ai"', nsis)
        self.assertIn("MUI_PAGE_WELCOME", nsis)
        self.assertIn("MUI_PAGE_LICENSE", nsis)
        self.assertIn("MUI_PAGE_DIRECTORY", nsis)
        self.assertIn("MUI_PAGE_INSTFILES", nsis)
        self.assertIn("MUI_PAGE_FINISH", nsis)
        self.assertIn("WriteUninstaller", nsis)
        self.assertIn('CreateDirectory "$INSTDIR\\Skills"', nsis)
        web = (ROOT / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "src" / "desktop" / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Full Device &amp; Network Access", web)
        self.assertIn("device-access-toggle", web)
        self.assertIn("ENABLE FULL ACCESS", app)
        self.assertIn("/api/device/inventory", app)


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
            script = shortcut_script(target, None, Path(result["desktop"]))
            self.assertIn('TargetPath = "' + str(target) + '"', script)
            self.assertIn('WorkingDirectory = "' + str(target.parent) + '"', script)

    def test_finds_packaged_exe(self) -> None:
        exe = find_app_executable(ROOT)
        self.assertTrue(str(exe).endswith("JonathanAi.exe"))


class TestDashboardHtml(unittest.TestCase):
    def test_glass_dashboard_and_conversation_list(self) -> None:
        html = (ROOT / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "src" / "desktop" / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("robot.png", html)
        self.assertIn("Conversations", html)
        self.assertIn("0.4.6", html)
        self.assertIn("session-menu", html)
        self.assertIn("working-robot", html)
        self.assertIn("working-progress", html)
        self.assertIn("preview-pane", html)
        self.assertIn("Connect tools", html)
        self.assertIn("Remove from sidebar", html)
        self.assertIn("Agent instances", html)
        self.assertIn("Local terminals", html)
        self.assertIn("Shared skills library", html)
        self.assertIn("skill-content", html)
        self.assertIn("standalone", html)
        self.assertIn("informational", html)
        self.assertIn("backdrop-filter", css)
        self.assertIn("glass", css)
        self.assertIn("robot-roam", css)
        self.assertIn("preview-open", css)
        main_js = (ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
        self.assertIn('app.setPath("userData", USER_DATA)', main_js)
        self.assertIn('".clawd", "electron"', main_js)
        self.assertIn("app.disableHardwareAcceleration()", main_js)
        self.assertIn('app.commandLine.appendSwitch("in-process-gpu")', main_js)
        self.assertIn("chooseAvailablePort", main_js)
        self.assertIn('path: "/api/ready"', main_js)
        self.assertIn('"desktop.log"', main_js)
        self.assertIn('"bootstrap_skipped"', main_js)
        self.assertIn("Starting Jonathan Ai", main_js)
        self.assertIn("let settled = false", main_js)
        self.assertIn('title: "Jonathan Ai 0.4.6"', main_js)
        self.assertIn('"window_created"', main_js)
        self.assertIn('"window_load_failed"', main_js)
        preload_js = (ROOT / "desktop" / "preload.js").read_text(encoding="utf-8")
        app_js = (ROOT / "src" / "desktop" / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("getPathForFile", preload_js)
        self.assertIn("data_base64", app_js)
        self.assertIn("appendConversationAttachment", app_js)
        self.assertNotIn("function addToolCard", app_js)
        self.assertNotIn("Buy tokens", html)
        self.assertNotIn("out of tokens", html)


if __name__ == "__main__":
    unittest.main()
