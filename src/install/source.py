"""Materialize and validate the GoDeskio/Clawd-Code source tree."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .constants import (
    ALLOWED_OWNER,
    ALLOWED_REPO,
    CANONICAL_HTTPS,
    JONATHAN_FOLDER_NAME,
    SOURCE_FOLDER_NAME,
)


class UntrustedSourceError(ValueError):
    """Raised when a git remote is not GoDeskio/Clawd-Code."""


def default_source_dir(home: Path | None = None) -> Path:
    """~/Jonathan/Clawd-Code or %USERPROFILE%\\Jonathan\\Clawd-Code."""
    root = Path(home) if home is not None else Path.home()
    return (root / JONATHAN_FOLDER_NAME / SOURCE_FOLDER_NAME).expanduser()


def parse_github_repo(url: str) -> tuple[str, str] | None:
    raw = (url or "").strip()
    if not raw:
        return None
    raw = raw.rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    ssh = re.match(r"^git@github\.com:([^/]+)/([^/]+)$", raw)
    if ssh:
        return ssh.group(1), ssh.group(2)
    ssh2 = re.match(r"^ssh://(?:git@)?github\.com/([^/]+)/([^/]+)$", raw)
    if ssh2:
        return ssh2.group(1), ssh2.group(2)
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme in {"http", "https"} and host in {"github.com", "www.github.com"}:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None


def is_allowed_source_url(url: str) -> bool:
    parsed = parse_github_repo(url)
    if parsed is None:
        return False
    owner, repo = parsed
    return owner.lower() == ALLOWED_OWNER and repo.lower() == ALLOWED_REPO


def assert_allowed_source_url(url: str) -> str:
    if not is_allowed_source_url(url):
        raise UntrustedSourceError(
            f"Refusing source that is not {CANONICAL_HTTPS}: {url or '(empty)'}"
        )
    return CANONICAL_HTTPS


def default_source_dir_display() -> str:
    return str(default_source_dir())


def _run_git(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=True,
        text=True,
    )


def read_remotes(repo: Path) -> dict[str, str]:
    if not (repo / ".git").exists():
        return {}
    result = _run_git(["remote", "-v"], cwd=repo, check=False)
    remotes: dict[str, str] = {}
    if result.returncode != 0:
        return remotes
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes[parts[0]] = parts[1]
    return remotes


def assert_repo_remotes_allowed(repo: Path) -> None:
    remotes = read_remotes(repo)
    if not remotes:
        raise UntrustedSourceError(f"no git remotes in {repo}")
    for name, url in remotes.items():
        if not is_allowed_source_url(url):
            raise UntrustedSourceError(
                f"remote {name} is not GoDeskio/Clawd-Code ({url})"
            )


def current_commit(repo: Path) -> str:
    result = _run_git(["rev-parse", "HEAD"], cwd=repo, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def current_branch(repo: Path) -> str:
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _copy_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.is_dir() and not any(dest.iterdir()):
        dest.rmdir()
    ignore = shutil.ignore_patterns(
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        "*.pyc",
        ".mypy_cache",
    )
    if dest.exists():
        return
    shutil.copytree(src, dest, ignore=ignore, dirs_exist_ok=False)


def materialize_source(
    dest: Path,
    *,
    from_local: Path | None = None,
    clone_url: str = CANONICAL_HTTPS,
    retry: int = 3,
) -> Path:
    """Clone or copy the GoDesk fork into dest.

    If dest already exists as a git repo, remotes are validated and the
    tree is reused. Otherwise clone from the allowlisted URL, or copy a
    local tree and force origin to GoDeskio/Clawd-Code.
    """
    dest = Path(dest).expanduser().resolve()
    assert_allowed_source_url(clone_url)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and (dest / ".git").exists():
        assert_repo_remotes_allowed(dest)
        _run_git(["remote", "set-url", "origin", CANONICAL_HTTPS], cwd=dest, check=False)
        assert_repo_remotes_allowed(dest)
        return dest

    if dest.exists() and any(dest.iterdir()):
        if (dest / "src" / "cli.py").exists():
            if (dest / ".git").exists():
                assert_repo_remotes_allowed(dest)
            return dest
        raise UntrustedSourceError(f"install directory is not empty: {dest}")

    last_error: Exception | None = None
    if from_local is not None:
        src = Path(from_local).expanduser().resolve()
        if (src / "src" / "cli.py").exists():
            _copy_tree(src, dest)
            if (dest / ".git").exists():
                remotes = read_remotes(dest)
                if "origin" in remotes:
                    _run_git(["remote", "set-url", "origin", CANONICAL_HTTPS], cwd=dest)
                else:
                    _run_git(["remote", "add", "origin", CANONICAL_HTTPS], cwd=dest)
                assert_repo_remotes_allowed(dest)
            else:
                _run_git(["init"], cwd=dest)
                _run_git(["remote", "add", "origin", CANONICAL_HTTPS], cwd=dest)
            return dest

    for attempt in range(1, retry + 1):
        try:
            if dest.exists():
                shutil.rmtree(dest)
            _run_git(["clone", "--origin", "origin", CANONICAL_HTTPS, str(dest)])
            assert_repo_remotes_allowed(dest)
            return dest
        except Exception as exc:
            last_error = exc
            if attempt >= retry:
                break
    raise RuntimeError(f"failed to materialize source after {retry} attempts: {last_error}")
