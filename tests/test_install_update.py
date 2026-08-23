"""Tests for the install wizard, Jonathan source path, and GoDesk-only updates."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.install.constants import CANONICAL_HTTPS
from src.install.python_env import detect_os, find_system_python
from src.install.record import read_install_record, write_install_record
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


class TestWizardAndVerify(unittest.TestCase):
    def test_detect_os_and_python(self) -> None:
        info = detect_os()
        self.assertIn("platform", info)
        self.assertTrue(find_system_python().exists())

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

    def test_status_compares_local_and_remote_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            updater = Updater(repo)
            local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            with patch("src.update.updater.fetch_repo_status", return_value={
                "sha": "deadbeef",
                "default_branch": "main",
                "release_tag": "",
                "html_url": "https://github.com/GoDeskio/Clawd-Code",
            }):
                status = updater.status(refresh=True)
            self.assertTrue(status["update_available"])
            self.assertEqual(status["local_sha"], local)
            self.assertEqual(status["remote_sha"], "deadbeef")

    def test_apply_refuses_dirty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            (repo / "dirty.txt").write_text("nope\n", encoding="utf-8")
            updater = Updater(repo)
            with self.assertRaises(RuntimeError):
                updater.apply()

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


if __name__ == "__main__":
    unittest.main()
