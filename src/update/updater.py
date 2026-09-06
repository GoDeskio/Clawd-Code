"""Self-update Jonathan from its allowlisted PR branch.

Developer checkouts fast-forward with Git. Packaged installs deliberately do
not rely on their excluded/stale ``.git`` directory: they download the setup
executable from the same allowlisted branch and ask the desktop shell to run it
after the current process exits.
"""

from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src.install.constants import CANONICAL_HTTPS, RAW_GITHUB_ROOT, UPDATE_BRANCH, UPDATE_INTERVAL_S, USER_AGENT
from src.install.deps import install_fooocus_dep, install_python_deps
from src.install.python_env import venv_python
from src.install.record import resolve_source_dir, write_install_record
from src.install.source import (
    UntrustedSourceError,
    assert_allowed_source_url,
    assert_repo_remotes_allowed,
    current_branch,
    current_commit,
    read_remotes,
)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


class Updater:
    def __init__(self, source_dir: str | Path | None = None) -> None:
        resolved = resolve_source_dir(source_dir) or Path.cwd()
        self.source_dir = Path(resolved).expanduser().resolve()
        self.last_check: dict[str, Any] | None = None
        self.last_check_at: float = 0.0

    def is_dirty(self) -> bool:
        if not (self.source_dir / ".git").exists():
            return True
        result = _git(["status", "--porcelain"], self.source_dir)
        return result.returncode != 0 or bool(result.stdout.strip())

    def local_version(self) -> str:
        try:
            return (self.source_dir / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return "0.0.0"

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        pieces: list[int] = []
        for part in str(value or "").strip().lstrip("v").split("."):
            digits = "".join(char for char in part if char.isdigit())
            pieces.append(int(digits or 0))
        return tuple((pieces + [0, 0, 0])[:3])

    @staticmethod
    def _read_url(url: str, *, timeout: float = 30.0) -> bytes:
        if not url.startswith(f"{RAW_GITHUB_ROOT}/"):
            raise ValueError("refusing update URL outside the allowlisted Jonathan branch")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub update download failed with HTTP {exc.code}") from exc

    def remote_version(self) -> str:
        value = self._read_url(f"{RAW_GITHUB_ROOT}/VERSION").decode("utf-8").strip()
        if not value or any(char not in "0123456789.v-" for char in value):
            raise RuntimeError("GitHub returned an invalid Jonathan version")
        return value.lstrip("v")

    def _git_update_capable(self, branch: str | None = None) -> bool:
        selected = branch if branch is not None else current_branch(self.source_dir)
        return bool(
            (self.source_dir / ".git").exists()
            and selected
            and selected not in {"HEAD", "main"}
            and not self.is_dirty()
        )

    def _packaged_install(self) -> bool:
        return (self.source_dir / "JonathanAi.exe").is_file()

    def _guard_tree(self) -> None:
        remotes = read_remotes(self.source_dir)
        if not remotes:
            raise UntrustedSourceError("install tree has no git remotes")
        for url in remotes.values():
            assert_allowed_source_url(url)
        assert_repo_remotes_allowed(self.source_dir)
        _git(["remote", "set-url", "origin", CANONICAL_HTTPS], self.source_dir)
        assert_repo_remotes_allowed(self.source_dir)

    def status(self, *, refresh: bool = False, interval_s: float = UPDATE_INTERVAL_S) -> dict[str, Any]:
        now = time.time()
        if not refresh and self.last_check and (now - self.last_check_at) < interval_s:
            return self.last_check
        local_sha = current_commit(self.source_dir)
        local_branch = current_branch(self.source_dir)
        local_version = self.local_version()
        payload: dict[str, Any] = {
            "source_dir": str(self.source_dir),
            "local_sha": local_sha,
            "local_branch": local_branch,
            "local_version": local_version,
            "repo": "GoDeskio/Clawd-Code",
            "track_branch": local_branch if local_branch not in {"", "HEAD", "main"} else UPDATE_BRANCH,
            "update_available": False,
            "checked_at": now,
        }
        try:
            remote_version = self.remote_version()
            payload["remote_version"] = remote_version
            payload["apply_mode"] = "installer"
            payload["dirty"] = self.is_dirty()
            remote_sha = ""
            git_capable = self._git_update_capable(local_branch)
            if git_capable:
                tracked_branch = str(payload["track_branch"])
                self._guard_tree()
                _git(["fetch", "origin", tracked_branch], self.source_dir)
                probed = _git(["rev-parse", f"origin/{tracked_branch}"], self.source_dir)
                if probed.returncode == 0:
                    remote_sha = probed.stdout.strip()
                payload["apply_mode"] = "git"
            payload["remote_sha"] = remote_sha
            version_newer = self._version_tuple(remote_version) > self._version_tuple(local_version)
            payload["update_available"] = bool(version_newer or (git_capable and remote_sha and remote_sha != local_sha))
            payload["html_url"] = "https://github.com/GoDeskio/Clawd-Code"
        except Exception as exc:
            payload["error"] = str(exc)
        self.last_check = payload
        self.last_check_at = now
        return payload

    def apply(self, *, allow_dirty: bool = False) -> dict[str, Any]:
        if (self.source_dir / ".git").exists():
            self._guard_tree()
        if self.is_dirty() and not self._packaged_install():
            raise RuntimeError("working tree has local changes; refusing to auto-update (commit or stash first)")
        checked = self.status(refresh=True)
        if checked.get("error"):
            raise RuntimeError(str(checked["error"]))
        if not checked.get("update_available"):
            return {
                "ok": True,
                "applied": False,
                "restart_required": False,
                "source_dir": str(self.source_dir),
                "version": self.local_version(),
            }
        if checked.get("apply_mode") != "git":
            return self._download_installer(str(checked.get("remote_version") or ""))

        self._guard_tree()
        branch = current_branch(self.source_dir)
        tracked_branch = str(checked.get("track_branch") or UPDATE_BRANCH)
        if branch != tracked_branch or branch == "main" or self.is_dirty():
            return self._download_installer(str(checked.get("remote_version") or ""))
        previous = current_commit(self.source_dir)
        fetch = _git(["fetch", "origin", tracked_branch], self.source_dir)
        if fetch.returncode != 0:
            raise RuntimeError(fetch.stderr.strip() or "git fetch failed")
        pull = _git(["merge", "--ff-only", f"origin/{tracked_branch}"], self.source_dir)
        if pull.returncode != 0:
            raise RuntimeError(pull.stderr.strip() or "fast-forward update failed")
        python = venv_python(self.source_dir)
        if python.exists():
            install_python_deps(python, self.source_dir, retry=3)
        install_fooocus_dep(self.source_dir)
        new_sha = current_commit(self.source_dir)
        write_install_record(
            source_dir=self.source_dir,
            venv_python=python if python.exists() else Path(self.source_dir / ".venv"),
            commit=new_sha,
            branch=current_branch(self.source_dir),
        )
        result = {
            "ok": True,
            "applied": True,
            "sha": new_sha,
            "previous": previous,
            "branch": tracked_branch,
            "apply_mode": "git",
            "restart_required": True,
            "source_dir": str(self.source_dir),
        }
        self.last_check = None
        return result

    def _download_installer(self, version: str) -> dict[str, Any]:
        if not version:
            raise RuntimeError("the remote Jonathan version is unavailable")
        update_dir = Path.home() / ".clawd" / "updates"
        update_dir.mkdir(parents=True, exist_ok=True)
        target = update_dir / f"JonathanAi-Setup-{version}.exe"
        partial = target.with_suffix(".exe.part")
        url = f"{RAW_GITHUB_ROOT}/JonathanAi-Setup.exe"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=300) as response, partial.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
            if partial.stat().st_size < 1024 * 1024 or partial.read_bytes()[:2] != b"MZ":
                raise RuntimeError("downloaded Jonathan installer failed validation")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return {
            "ok": True,
            "applied": False,
            "downloaded": True,
            "apply_mode": "installer",
            "installer_path": str(target),
            "version": version,
            "branch": UPDATE_BRANCH,
            "restart_required": True,
            "source_dir": str(self.source_dir),
        }
