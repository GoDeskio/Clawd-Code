"""Local git operations used by GitHub and GitLab connectors.

Never writes credentials into .git/config. Default branches are not pushed
unless the operator explicitly named that branch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_BRANCH_NAMES = frozenset({"main", "master", "trunk", "develop"})


class GitRuleError(ValueError):
    """Raised when a git action would violate branch-then-PR rules."""


def run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    token: str | None = None,
    extra_header: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = ["git"]
    header = extra_header
    if token and not header:
        header = f"Authorization: Bearer {token}"
    if header:
        cmd.extend(["-c", f"http.extraHeader={header}"])
    cmd.extend(args)
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, env=env, check=False)
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "git failed").strip()
        raise RuntimeError(err)
    return result


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists() or run_git(["rev-parse", "--is-inside-work-tree"], cwd=path, check=False).returncode == 0


def repo_root(path: Path) -> Path | None:
    result = run_git(["rev-parse", "--show-toplevel"], cwd=path, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def current_branch(path: Path) -> str:
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path, check=False)
    return (result.stdout or "").strip()


def default_branch(path: Path, fallback: str = "main") -> str:
    result = run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=path, check=False)
    text = (result.stdout or "").strip()
    if text.startswith("origin/"):
        return text.split("/", 1)[1]
    for name in ("main", "master"):
        probe = run_git(["show-ref", "--verify", f"refs/heads/{name}"], cwd=path, check=False)
        if probe.returncode == 0:
            return name
    return fallback


def assert_push_allowed(branch: str, *, default: str, operator_named: bool) -> str:
    named = (branch or "").strip()
    if not named:
        raise GitRuleError("Name the branch to push. Jonathan Ai will not guess the default branch.")
    target_default = (default or "main").strip() or "main"
    if named == target_default and not operator_named:
        raise GitRuleError(
            f"Refusing to push default branch {target_default!r}. "
            "Create a feature branch and open a PR, or name that branch explicitly."
        )
    if named in DEFAULT_BRANCH_NAMES and named == target_default and not operator_named:
        raise GitRuleError(f"Refusing to push {named!r} without an explicit operator-named branch.")
    return named


def clone_repo(url: str, dest: Path, *, token: str | None = None, extra_header: str | None = None) -> Path:
    dest = dest.expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and is_git_repo(dest):
        pull_repo(dest, token=token, extra_header=extra_header)
        return dest
    run_git(["clone", "--origin", "origin", url, str(dest)], token=token, extra_header=extra_header)
    return dest


def pull_repo(path: Path, *, token: str | None = None, extra_header: str | None = None) -> dict[str, Any]:
    fetch = run_git(["fetch", "origin"], cwd=path, token=token, extra_header=extra_header, check=False)
    if fetch.returncode != 0:
        raise RuntimeError((fetch.stderr or fetch.stdout or "git fetch failed").strip())
    branch = current_branch(path)
    pull = run_git(["merge", "--ff-only", f"origin/{branch}"], cwd=path, token=token, extra_header=extra_header, check=False)
    if pull.returncode != 0:
        # Empty upstream is fine for a brand-new branch.
        return {"ok": True, "branch": branch, "note": (pull.stderr or "").strip() or "fetched"}
    return {"ok": True, "branch": branch, "pulled": True}


def ensure_branch(path: Path, branch: str) -> str:
    name = (branch or "").strip()
    if not name:
        raise GitRuleError("branch name is required")
    current = current_branch(path)
    if current == name:
        return name
    existing = run_git(["show-ref", "--verify", f"refs/heads/{name}"], cwd=path, check=False)
    if existing.returncode == 0:
        run_git(["checkout", name], cwd=path)
    else:
        run_git(["checkout", "-b", name], cwd=path)
    return name


def push_branch(
    path: Path,
    branch: str,
    *,
    token: str | None = None,
    extra_header: str | None = None,
    default: str | None = None,
    operator_named: bool = False,
    remote: str = "origin",
) -> dict[str, Any]:
    repo = repo_root(path) or path
    detected_default = default or default_branch(repo)
    named = assert_push_allowed(branch, default=detected_default, operator_named=operator_named)
    ensure_branch(repo, named)
    run_git(
        ["push", "-u", remote, f"HEAD:refs/heads/{named}"],
        cwd=repo,
        token=token,
        extra_header=extra_header,
    )
    return {"ok": True, "branch": named, "default_branch": detected_default, "remote": remote}


def workspace_git_status(path: Path) -> dict[str, Any]:
    root = repo_root(path)
    if root is None:
        return {"is_repo": False, "path": str(path)}
    status = run_git(["status", "--porcelain", "-b"], cwd=root, check=False)
    return {
        "is_repo": True,
        "path": str(root),
        "branch": current_branch(root),
        "default_branch": default_branch(root),
        "dirty": bool((status.stdout or "").splitlines()[1:] if status.stdout else False) or bool(
            any(line and not line.startswith("##") for line in (status.stdout or "").splitlines())
        ),
        "status": (status.stdout or "").strip(),
    }
