"""Tests for the install wizard, Jonathan source path, and GoDesk-only updates."""

from __future__ import annotations

import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.install.constants import CANONICAL_HTTPS
from src.install.python_env import detect_os, ensure_venv, find_system_python, venv_is_usable
from src.install.record import read_install_record, write_install_record
from src.install.deps import install_desktop_deps
from src.install.runtime_process import (
    process_record_path,
    read_process_record,
    stop_running_app,
    write_process_record,
)
from src.install.source import (
    UntrustedSourceError,
    assert_allowed_source_url,
    default_source_dir,
    is_allowed_source_url,
    materialize_source,
)
from src.install.verify import verify_agent_session
from src.install.wizard import InstallWizard, write_provider_placeholders
from src.update.updater import Updater


class TestJonathanPath(unittest.TestCase):
    def test_default_source_dir_is_jonathan_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = default_source_dir(home=Path(tmp))
            self.assertEqual(dest, Path(tmp) / "Jonathan" / "Jonathan-Ai")


class TestRuntimeProcessRecord(unittest.TestCase):
    def test_record_is_scoped_to_install_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Jonathan" / "Jonathan-Ai"
            root.mkdir(parents=True)
            write_process_record(root, owner_pid=99991, backend_pid=99992, kind="electron")
            record = read_process_record(root)
            self.assertEqual(record["source_dir"], str(root.resolve()))
            self.assertEqual(record["owner_pid"], 99991)
            self.assertIsNone(read_process_record(root.parent))

    def test_windows_stop_targets_only_recorded_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_process_record(root, owner_pid=99991, backend_pid=99992, kind="electron")
            completed = subprocess.CompletedProcess([], 0, "", "")
            image = str(root / "desktop" / "node_modules" / "electron" / "dist" / "electron.exe")
            with patch("src.install.runtime_process._pid_is_running", return_value=(True, image)), patch(
                "src.install.runtime_process.shutil.which", return_value="taskkill.exe"
            ), patch("src.install.runtime_process.subprocess.run", return_value=completed) as run:
                result = stop_running_app(root)
            self.assertTrue(result["was_running"])
            self.assertTrue(result["stopped"])
            taskkill_calls = [
                call.args[0]
                for call in run.call_args_list
                if call.args and isinstance(call.args[0], list) and "/PID" in call.args[0]
            ]
            self.assertTrue(taskkill_calls)
            self.assertIn("99991", taskkill_calls[-1])
            self.assertFalse(process_record_path(root).exists())

    def test_reused_pid_outside_install_root_is_never_killed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_process_record(root, owner_pid=99991, kind="electron")
            with patch(
                "src.install.runtime_process._pid_is_running",
                return_value=(True, r"C:\OtherApp\electron.exe"),
            ), patch("src.install.runtime_process.subprocess.run") as run:
                result = stop_running_app(root)
            self.assertFalse(result["was_running"])
            self.assertIn("unexpected executable", result["error"])
            kill_calls = [
                call.args[0]
                for call in run.call_args_list
                if call.args and isinstance(call.args[0], list) and "/PID" in call.args[0]
            ]
            self.assertEqual(kill_calls, [])
            self.assertTrue(process_record_path(root).exists())


class TestSourceAllowlist(unittest.TestCase):
    def test_accepts_godesk_urls(self) -> None:
        for url in (
            "https://github.com/GoDeskio/Clawd-Code.git",
            "https://github.com/GoDeskio/Clawd-Code",
            "git@github.com:GoDeskio/Clawd-Code.git",
            "ssh://git@github.com/GoDeskio/Clawd-Code.git",
            "https://x-access-token:example@github.com/GoDeskio/Clawd-Code.git",
        ):
            self.assertTrue(is_allowed_source_url(url), url)
            self.assertEqual(assert_allowed_source_url(url), CANONICAL_HTTPS)

    def test_rejects_upstream_and_other_remotes(self) -> None:
        for url in (
            "https://github.com/GPT-AGI/Clawd-Code.git",
            "https://github.com/evil/malware.git",
            "https://example.com/GoDeskio/Clawd-Code.git",
            "",
        ):
            self.assertFalse(is_allowed_source_url(url), url)
            with self.assertRaises(UntrustedSourceError):
                assert_allowed_source_url(url)


class TestMaterializeSource(unittest.TestCase):
    def test_copies_local_tree_and_forces_godesk_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "checkout"
            dest = Path(tmp) / "Jonathan" / "Jonathan-Ai"
            (src / "src").mkdir(parents=True)
            (src / "src" / "cli.py").write_text("print('ok')\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=src, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/GPT-AGI/Clawd-Code.git"], cwd=src, check=True, capture_output=True)
            tree = materialize_source(dest, from_local=src)
            self.assertTrue((tree / "src" / "cli.py").exists())
            remotes = subprocess.run(["git", "remote", "-v"], cwd=tree, check=True, capture_output=True, text=True)
            self.assertIn("GoDeskio/Clawd-Code", remotes.stdout)
            self.assertNotIn("GPT-AGI", remotes.stdout)

    def test_existing_feature_branch_is_not_merged_with_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "Jonathan" / "Jonathan-Ai"
            dest.mkdir(parents=True)
            (dest / "src").mkdir()
            (dest / "src" / "cli.py").write_text("print('old')\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", CANONICAL_HTTPS], cwd=dest, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "add", "src/cli.py"], cwd=dest, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"], cwd=dest, check=True, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "cursor/desktop-agent-shell-e032"], cwd=dest, check=True, capture_output=True)
            src = Path(tmp) / "checkout"
            (src / "src").mkdir(parents=True)
            (src / "src" / "cli.py").write_text("print('overlay')\n", encoding="utf-8")
            calls: list[list[str]] = []

            def record(args, *, cwd=None, check=True):
                calls.append(list(args))
                return subprocess.CompletedProcess(["git", *args], 0, "", "")

            with patch("src.install.source._run_git", side_effect=record):
                tree = materialize_source(dest, from_local=src)
            self.assertEqual((tree / "src" / "cli.py").read_text(encoding="utf-8"), "print('overlay')\n")
            merged = [" ".join(args) for args in calls if args and args[0] == "merge"]
            self.assertFalse(any("origin/main" in item for item in merged), merged)


class TestWizardAndVerify(unittest.TestCase):
    def test_detect_os_and_python(self) -> None:
        info = detect_os()
        self.assertIn("platform", info)
        self.assertTrue(find_system_python().exists())

    def test_ensure_venv_recreates_broken_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "app"
            broken = source / ".venv" / "bin" / "python"
            if __import__("os").name == "nt":
                broken = source / ".venv" / "Scripts" / "python.exe"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("not-a-python", encoding="utf-8")
            self.assertFalse(venv_is_usable(source))

            def fake_run(cmd, **kwargs):
                joined = " ".join(str(part) for part in cmd)
                if "-m" in cmd and "venv" in cmd:
                    target = source / ".venv" / ("Scripts" if __import__("os").name == "nt" else "bin")
                    if (source / ".venv").exists():
                        import shutil
                        shutil.rmtree(source / ".venv", ignore_errors=True)
                    target.mkdir(parents=True, exist_ok=True)
                    exe = target / ("python.exe" if __import__("os").name == "nt" else "python")
                    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    exe.chmod(0o755)
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if str(broken) in joined or str(source / ".venv") in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "broken venv")
                return subprocess.CompletedProcess(cmd, 0, "3.12", "")

            with patch("src.install.python_env.subprocess.run", side_effect=fake_run), patch(
                "src.install.python_env.find_system_python", return_value=Path("/usr/bin/python3")
            ):
                created = ensure_venv(source)
            self.assertTrue(created.exists())
            self.assertIn("exit 0", created.read_text(encoding="utf-8"))

    def test_placeholders_do_not_write_keys_into_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            with patch("src.config.Path.home", return_value=home):
                write_provider_placeholders()
                config = json.loads((home / ".clawd" / "config.json").read_text())
                for provider in config["providers"].values():
                    self.assertEqual(provider.get("api_key"), "")
                self.assertFalse((Path.cwd() / "config.json").exists())

    def test_verify_creates_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("src.config.Path.home", return_value=home), patch("src.agent.session.Path.home", return_value=home):
                result = verify_agent_session(workspace)
            self.assertTrue(result["ok"])
            self.assertTrue(result["session_id"])

    def test_wizard_sync_with_mocked_deps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            src = Path(tmp) / "checkout"
            dest = Path(tmp) / "Jonathan" / "Jonathan-Ai"
            (src / "src").mkdir(parents=True)
            (src / "src" / "cli.py").write_text("# cli\n", encoding="utf-8")
            (src / "requirements.txt").write_text("rich\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=src, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", CANONICAL_HTTPS], cwd=src, check=True, capture_output=True)
            fake_python = Path(tmp) / "python"
            fake_python.write_text("#!/bin/sh\n", encoding="utf-8")
            events: list[str] = []

            def fake_venv(source_dir, python=None):
                venv = Path(source_dir) / ".venv" / "bin" / "python"
                venv.parent.mkdir(parents=True, exist_ok=True)
                venv.write_text("", encoding="utf-8")
                return venv

            with patch("src.config.Path.home", return_value=home), patch(
                "src.agent.session.Path.home", return_value=home
            ), patch(
                "src.install.record.Path.home", return_value=home
            ), patch("src.install.wizard.find_system_python", return_value=fake_python), patch(
                "src.install.wizard.ensure_venv", side_effect=fake_venv
            ), patch(
                "src.install.wizard.install_python_deps"
            ), patch(
                "src.install.wizard.install_desktop_deps", return_value="skipped"
            ), patch(
                "src.install.wizard.install_blender_dep", return_value="ready"
            ), patch(
                "src.install.wizard.install_ecc_dep", return_value="ready"
            ), patch(
                "src.install.wizard.install_kronos_dep", return_value="ready"
            ), patch(
                "src.install.wizard.install_personal_finance_dep", return_value="ready"
            ), patch(
                "src.install.wizard.install_code_memory_dep", return_value="ready"
            ), patch(
                "src.install.wizard.install_procoder_dep", return_value="ready"
            ), patch(
                "src.install.wizard.install_drawai_dep", return_value="ready"
            ), patch(
                "src.install.wizard.verify_agent_session", return_value={"ok": True, "session_id": "s"}
            ):
                result = InstallWizard().run_sync(
                    source_dir=dest,
                    from_local=src,
                    skip_desktop_deps=True,
                    progress=lambda e: events.append(e.get("type") or ""),
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["source_dir"], str(dest.resolve()))
            self.assertTrue((dest / "start-desktop.sh").exists())
            record = read_install_record(home=home)
            self.assertIsNotNone(record)
            self.assertIn("Jonathan", record["source_dir"])
            self.assertIn("done", events)


class TestUpdater(unittest.TestCase):
    def _repo(self, tmp: Path) -> Path:
        repo = tmp / "Jonathan" / "Jonathan-Ai"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", CANONICAL_HTTPS], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("ok\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        return repo

    def test_refuses_non_godesk_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "evil"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/GPT-AGI/Clawd-Code.git"], cwd=repo, check=True, capture_output=True)
            updater = Updater(repo)
            with self.assertRaises(UntrustedSourceError):
                updater.apply()

    def test_status_compares_local_and_origin_of_current_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            updater = Updater(repo)
            local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            calls: list[list[str]] = []

            def fake_git(args, cwd):
                calls.append(list(args))
                if args[:2] == ["rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(["git", *args], 0, local + "\n", "")
                if args[:1] == ["rev-parse"] and str(args[1]).startswith("origin/"):
                    return subprocess.CompletedProcess(["git", *args], 0, "deadbeef\n", "")
                if args[:2] == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(["git", *args], 0, "", "")
                if args[:2] == ["remote", "-v"]:
                    return subprocess.CompletedProcess(["git", *args], 0, f"origin\t{CANONICAL_HTTPS} (fetch)\n", "")
                return subprocess.CompletedProcess(["git", *args], 0, "", "")

            with patch("src.update.updater._git", side_effect=fake_git), patch(
                "src.update.updater.fetch_repo_status", return_value={
                    "sha": "mainsha",
                    "default_branch": "main",
                    "release_tag": "",
                    "html_url": "https://github.com/GoDeskio/Clawd-Code",
                }
            ):
                status = updater.status(refresh=True)
            self.assertTrue(status["update_available"])
            self.assertEqual(status["local_sha"], local)
            self.assertEqual(status["remote_sha"], "deadbeef")
            self.assertNotEqual(status["remote_sha"], "mainsha")
            self.assertFalse(any(item[:1] == ["merge"] and "origin/main" in " ".join(item) for item in calls))

    def test_apply_refuses_dirty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            (repo / "dirty.txt").write_text("nope\n", encoding="utf-8")
            updater = Updater(repo)
            with self.assertRaises(RuntimeError):
                updater.apply()

    def test_allow_dirty_cannot_bypass_update_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            (repo / "dirty.txt").write_text("must survive\n", encoding="utf-8")
            updater = Updater(repo)
            with self.assertRaises(RuntimeError):
                updater.apply(allow_dirty=True)
            self.assertEqual((repo / "dirty.txt").read_text(encoding="utf-8"), "must survive\n")

    def test_install_record_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = write_install_record(
                source_dir=home / "Jonathan" / "Jonathan-Ai",
                venv_python=home / "Jonathan" / "Jonathan-Ai" / ".venv" / "bin" / "python",
                commit="abc",
                branch="main",
                home=home,
            )
            self.assertTrue(path.exists())
            data = read_install_record(home=home)
            self.assertEqual(data["repo"], CANONICAL_HTTPS)
            self.assertIn("Jonathan", data["source_dir"])
            self.assertNotIn("token", data)
            self.assertNotIn("api_key", data)

    def test_electron_install_failure_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "app"
            desktop = source / "desktop"
            desktop.mkdir(parents=True)
            (desktop / "package.json").write_text("{}", encoding="utf-8")
            notes: list[str] = []
            with patch("shutil.which", return_value="/usr/bin/npm"), patch(
                "src.install.deps._run", side_effect=RuntimeError("npm exploded")
            ):
                status = install_desktop_deps(source, retry=2, progress=notes.append)
            self.assertEqual(status, "failed")
            self.assertTrue(any("browser UI still works" in note for note in notes))

    def test_electron_uses_app_cache_and_requires_runtime_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "app"
            desktop = source / "desktop"
            desktop.mkdir(parents=True)
            (desktop / "package.json").write_text("{}", encoding="utf-8")
            captured: dict[str, str] = {}

            def install(_cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
                self.assertEqual(cwd, desktop)
                captured.update(env or {})
                binary = desktop / "node_modules" / "electron" / "dist" / ("electron.exe" if os.name == "nt" else "electron")
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"electron")

            with patch("shutil.which", return_value="npm"), patch("src.install.deps._run", side_effect=install):
                status = install_desktop_deps(source, retry=1)
            self.assertEqual(status, "installed")
            self.assertEqual(captured["ELECTRON_CACHE"], str(source / ".cache" / "electron"))
            self.assertEqual(captured["electron_config_cache"], str(source / ".cache" / "electron"))
            self.assertEqual(captured["NPM_CONFIG_CACHE"], str(source / ".cache" / "npm"))

    def test_electron_repairs_package_missing_its_downloaded_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "app"
            desktop = source / "desktop"
            desktop.mkdir(parents=True)
            (desktop / "package.json").write_text("{}", encoding="utf-8")
            installer = desktop / "node_modules" / "electron" / "install.js"
            installer.parent.mkdir(parents=True)
            installer.write_text("// installer", encoding="utf-8")
            commands: list[list[str]] = []

            def install(command: list[str], **_kwargs: object) -> None:
                commands.append(command)
                if command[-1].endswith("install.js"):
                    binary = desktop / "node_modules" / "electron" / "dist" / ("electron.exe" if os.name == "nt" else "electron")
                    binary.parent.mkdir(parents=True)
                    binary.write_bytes(b"electron")

            with patch("shutil.which", side_effect=lambda name: name), patch("src.install.deps._run", side_effect=install):
                status = install_desktop_deps(source, retry=1)
            self.assertEqual(status, "installed")
            self.assertEqual(commands, [["npm", "install"], ["node", str(installer)]])

    def test_wizard_html_covers_git_and_agents(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "install" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("GitHub", html)
        self.assertIn("GitLab", html)
        self.assertIn("MCP", html)
        self.assertIn("Clone GoDeskio/Clawd-Code", html)


if __name__ == "__main__":
    unittest.main()
