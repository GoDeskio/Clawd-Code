"""Talk to GitHub only for GoDeskio/Clawd-Code."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from src.install.constants import GITHUB_API_REPO, USER_AGENT
from src.install.source import assert_allowed_source_url


def _get_json(url: str, timeout: float = 15.0) -> dict[str, Any]:
    if "api.github.com/repos/GoDeskio/Clawd-Code" not in url:
        raise ValueError(f"refusing GitHub URL outside GoDeskio/Clawd-Code: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API error {exc.code} for {url}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub API returned a non-object")
    return payload


def fetch_repo_status() -> dict[str, Any]:
    repo = _get_json(GITHUB_API_REPO)
    clone_url = str(repo.get("clone_url") or "")
    assert_allowed_source_url(clone_url or "https://github.com/GoDeskio/Clawd-Code.git")
    default_branch = str(repo.get("default_branch") or "main")
    head = _get_json(f"{GITHUB_API_REPO}/commits/{default_branch}")
    sha = str(head.get("sha") or "")
    release_tag = ""
    try:
        release = _get_json(f"{GITHUB_API_REPO}/releases/latest")
        release_tag = str(release.get("tag_name") or "")
    except Exception:
        release_tag = ""
    return {
        "repo": "GoDeskio/Clawd-Code",
        "default_branch": default_branch,
        "sha": sha,
        "release_tag": release_tag,
        "html_url": "https://github.com/GoDeskio/Clawd-Code",
    }
