"""Self-update the Jonathan install from GoDeskio/Clawd-Code only."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from src.install.constants import CANONICAL_HTTPS, UPDATE_INTERVAL_S
from src.install.deps import install_fooocus_dep, install_python_deps
from src.install.python_env import venv_python
from src.install.record import read_install_record, resolve_source_dir, write_install_record
from src.install.source import (
    UntrustedSourceError,
    assert_allowed_source_url,
    assert_repo_remotes_allowed,
    current_branch,
    current_commit,
    read_remotes,
)
from src.update.github import fetch_repo_status


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


class Updater:
    def __init__(self, source_dir: str | Path | None = None) -> None:
        resolved = resolve_source_dir(source_dir) or Path.cwd()
        self.source_dir = Path(resolved).expanduser().resolve()
        self.last_check: dict[str, Any] | None = None
        self.last_check_at: float = 0.0

    def is_dirty(self) -> bool:
        result = _git(["status", "--porcelain"], self.source_dir)
        return result.returncode != 0 or bool(result.stdout.strip())

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
        payload: dict[str, Any] = {
            "source_dir": str(self.source_dir),
            "local_sha": local_sha,
            "local_branch": local_branch,
            "repo": "GoDeskio/Clawd-Code",
            "update_available": False,
            "checked_at": now,
        }
        try:
            self._guard_tree()
            _git(["fetch", "origin"], self.source_dir)
            branch = local_branch if local_branch and local_branch != "HEAD" else ""
            remote_sha = ""
            if branch:
                probed = _git(["rev-parse", f"origin/{branch}"], self.source_dir)
                if probed.returncode == 0:
                    remote_sha = probed.stdout.strip()
            payload["track_branch"] = branch
            payload["remote_sha"] = remote_sha
            # Only the current branch. Never treat origin/main as an update
            # for a feature-branch install.
            payload["update_available"] = bool(remote_sha and remote_sha != local_sha)
            payload["dirty"] = self.is_dirty()
            try:
                remote = fetch_repo_status()
                payload["default_branch"] = remote.get("default_branch")
                payload["release_tag"] = remote.get("release_tag")
                payload["html_url"] = remote.get("html_url")
            except Exception:
                pass
        except Exception as exc:
            payload["error"] = str(exc)
        self.last_check = payload
        self.last_check_at = now
        return payload

    def apply(self, *, allow_dirty: bool = False) -> dict[str, Any]:
        self._guard_tree()
        # Never let an automatic update overwrite local work. ``allow_dirty``
        # remains in the signature for compatibility but intentionally grants
        # no bypass; users must commit/stash their changes themselves.
        if self.is_dirty():
            raise RuntimeError("working tree has local changes; refusing to auto-update (commit or stash first)")
        local_branch = current_branch(self.source_dir)
        if not local_branch or local_branch == "HEAD":
            raise RuntimeError("detached HEAD; refusing auto-update")
        # Stay on the installed branch. Never check out or merge main into a
        # feature-branch install of this PR.
        branch = local_branch
        fetch = _git(["fetch", "origin", branch], self.source_dir)
        if fetch.returncode != 0:
            raise RuntimeError(fetch.stderr.strip() or "git fetch failed")
        pull = _git(["merge", "--ff-only", f"origin/{branch}"], self.source_dir)
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
        record = read_install_record() or {}
        result = {
            "ok": True,
            "applied": True,
            "sha": new_sha,
            "previous": record.get("commit"),
            "branch": branch,
            "restart_required": True,
            "source_dir": str(self.source_dir),
        }
        self.last_check = None
        return result
