"""One-click create-repo-and-push from a workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .git_common import current_branch, default_branch, ensure_branch, is_git_repo, run_git
from .github import GitHubConnector
from .gitlab import GitLabConnector
from .store import DEFAULT_GITHUB_OWNER


def _ensure_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if not is_git_repo(path):
        run_git(["init"], cwd=path)
    return path


def _ensure_remote(path: Path, url: str, name: str = "origin") -> None:
    existing = run_git(["remote", "get-url", name], cwd=path, check=False)
    if existing.returncode != 0:
        run_git(["remote", "add", name, url], cwd=path)
    else:
        run_git(["remote", "set-url", name, url], cwd=path)


def publish_workspace(
    path: str | Path,
    *,
    forge: str = "github",
    name: str | None = None,
    owner: str | None = None,
    branch: str | None = None,
    title: str | None = None,
    open_review: bool = True,
    operator_named_branch: bool = False,
) -> dict[str, Any]:
    root = _ensure_repo(Path(path).expanduser().resolve())
    repo_name = (name or root.name).strip()
    feature = (branch or f"jonathan/{repo_name}").strip()
    detected_default = default_branch(root)
    if not operator_named_branch and feature == detected_default:
        feature = f"jonathan/{repo_name}"
    ensure_branch(root, feature)
    if current_branch(root) in {detected_default, "HEAD"} and not operator_named_branch:
        ensure_branch(root, feature)

    if forge == "gitlab":
        gl = GitLabConnector(owner=owner)
        created = gl.create_project(repo_name, owner=owner)
        clone_url = created["clone_url"]
        _ensure_remote(root, clone_url)
        pushed = gl.push_branch(
            root,
            feature,
            operator_named=operator_named_branch,
            default_branch=created.get("default_branch") or detected_default,
        )
        review = None
        if open_review:
            review = gl.create_merge_request(
                created["full_name"],
                title=title or f"Add {repo_name}",
                source=feature,
                target=created.get("default_branch"),
            )
        return {"ok": True, "forge": "gitlab", "repo": created, "push": pushed, "review": review}

    gh = GitHubConnector(owner=owner or DEFAULT_GITHUB_OWNER)
    created = gh.create_repo(repo_name, owner=owner or gh.owner)
    clone_url = created["clone_url"]
    _ensure_remote(root, clone_url)
    pushed = gh.push_branch(
        root,
        feature,
        operator_named=operator_named_branch,
        default_branch=created.get("default_branch") or detected_default,
    )
    review = None
    if open_review:
        review = gh.create_pull_request(
            created["full_name"],
            title=title or f"Add {repo_name}",
            head=feature,
            base=created.get("default_branch"),
        )
    return {"ok": True, "forge": "github", "repo": created, "push": pushed, "review": review}
