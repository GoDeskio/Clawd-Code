"""GitHub connector. User-initiated only. Default create-owner is GoDeskio."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .git_common import clone_repo, pull_repo, push_branch, workspace_git_status
from .httputil import ConnectorHttpError, request_json
from .store import DEFAULT_GITHUB_OWNER, read_connectors, save_forge_login

API = "https://api.github.com"
DEVICE_CODE = "https://github.com/login/device/code"
DEVICE_TOKEN = "https://github.com/login/oauth/access_token"


class GitHubConnector:
    def __init__(self, token: str | None = None, owner: str | None = None) -> None:
        data = read_connectors()["github"]
        self.token = (token if token is not None else data.get("token") or "").strip()
        self.owner = (owner if owner is not None else data.get("owner") or DEFAULT_GITHUB_OWNER).strip() or DEFAULT_GITHUB_OWNER

    def require_token(self) -> str:
        if not self.token:
            raise ValueError("GitHub is not connected. Paste a token in settings or start device login.")
        return self.token

    def _api(self, path: str, *, method: str = "GET", body: Any = None) -> Any:
        return request_json(
            f"{API}{path}",
            method=method,
            token=self.require_token(),
            headers={"X-GitHub-Api-Version": "2022-11-28"},
            body=body,
        )

    def login_with_token(self, token: str, owner: str | None = None) -> dict[str, Any]:
        self.token = token.strip()
        me = self.whoami()
        save_forge_login(
            "github",
            token=self.token,
            owner=owner if owner is not None else self.owner,
            login=str(me.get("login") or ""),
            auth="token",
        )
        return {"ok": True, "login": me.get("login"), "owner": owner or self.owner}

    def whoami(self) -> dict[str, Any]:
        return self._api("/user")

    def list_repos(self, owner: str | None = None) -> list[dict[str, Any]]:
        target = (owner or self.owner or "").strip()
        path = f"/orgs/{target}/repos?per_page=50&sort=updated" if target else "/user/repos?per_page=50&sort=updated"
        try:
            payload = self._api(path)
        except ConnectorHttpError:
            payload = self._api("/user/repos?per_page=50&sort=updated")
        rows = payload if isinstance(payload, list) else []
        return [
            {
                "full_name": item.get("full_name"),
                "clone_url": item.get("clone_url"),
                "default_branch": item.get("default_branch") or "main",
                "private": bool(item.get("private")),
                "html_url": item.get("html_url"),
            }
            for item in rows
            if isinstance(item, dict)
        ]

    def create_repo(self, name: str, *, owner: str | None = None, private: bool = True, description: str = "") -> dict[str, Any]:
        target = (owner or self.owner or DEFAULT_GITHUB_OWNER).strip() or DEFAULT_GITHUB_OWNER
        body = {"name": name, "private": private, "description": description, "auto_init": False}
        if target and target != (self.whoami().get("login") or ""):
            created = self._api(f"/orgs/{target}/repos", method="POST", body=body)
        else:
            created = self._api("/user/repos", method="POST", body=body)
        return {
            "full_name": created.get("full_name"),
            "clone_url": created.get("clone_url"),
            "html_url": created.get("html_url"),
            "default_branch": created.get("default_branch") or "main",
            "owner": target,
        }

    def clone(self, repo: str, dest: str | Path) -> dict[str, Any]:
        url = repo if repo.startswith("http") else f"https://github.com/{repo}.git"
        path = clone_repo(url, Path(dest), token=self.require_token())
        return {"ok": True, "path": str(path), "url": url}

    def pull(self, dest: str | Path) -> dict[str, Any]:
        return pull_repo(Path(dest), token=self.require_token())

    def push_branch(
        self,
        dest: str | Path,
        branch: str,
        *,
        operator_named: bool = False,
        default_branch: str | None = None,
    ) -> dict[str, Any]:
        return push_branch(
            Path(dest),
            branch,
            token=self.require_token(),
            default=default_branch,
            operator_named=operator_named,
        )

    def create_pull_request(
        self,
        repo: str,
        *,
        title: str,
        head: str,
        base: str | None = None,
        body: str = "",
    ) -> dict[str, Any]:
        owner_repo = repo.replace("https://github.com/", "").replace(".git", "").strip("/")
        info = self._api(f"/repos/{owner_repo}")
        default = base or info.get("default_branch") or "main"
        if head == default:
            raise ValueError("Open a PR from a feature branch, not from the default branch.")
        pr = self._api(
            f"/repos/{owner_repo}/pulls",
            method="POST",
            body={"title": title, "head": head, "base": default, "body": body},
        )
        return {
            "number": pr.get("number"),
            "html_url": pr.get("html_url"),
            "head": head,
            "base": default,
        }

    def status(self, path: str | Path) -> dict[str, Any]:
        return workspace_git_status(Path(path))


def start_github_device_login(client_id: str, scope: str = "repo user") -> dict[str, Any]:
    """GitHub device flow. Requires a real OAuth App client_id supplied by the user."""
    cid = (client_id or "").strip()
    if not cid:
        raise ValueError(
            "Device login needs a GitHub OAuth App client ID. "
            "Create one at https://github.com/settings/developers or paste a personal access token instead."
        )
    from urllib.request import Request, urlopen

    req = Request(
        DEVICE_CODE,
        data=urlencode({"client_id": cid, "scope": scope}).encode(),
        headers={"Accept": "application/json", "User-Agent": "JonathanAi/0.1"},
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        payload = __import__("json").loads(resp.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(payload.get("error_description") or payload["error"])
    return {
        "device_code": payload.get("device_code"),
        "user_code": payload.get("user_code"),
        "verification_uri": payload.get("verification_uri") or "https://github.com/login/device",
        "interval": int(payload.get("interval") or 5),
        "expires_in": int(payload.get("expires_in") or 900),
        "client_id": cid,
        "message": f"Open {payload.get('verification_uri')} and enter {payload.get('user_code')}",
    }


def poll_github_device_login(client_id: str, device_code: str) -> dict[str, Any]:
    from urllib.request import Request, urlopen
    import json

    req = Request(
        DEVICE_TOKEN,
        data=urlencode({
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode(),
        headers={"Accept": "application/json", "User-Agent": "JonathanAi/0.1"},
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("error") == "authorization_pending":
        return {"pending": True}
    if payload.get("error") == "slow_down":
        time.sleep(5)
        return {"pending": True}
    if payload.get("error"):
        raise RuntimeError(payload.get("error_description") or payload["error"])
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("GitHub device login did not return a token")
    result = GitHubConnector().login_with_token(token)
    result["auth"] = "device"
    save_forge_login("github", token=token, owner=result.get("owner") or DEFAULT_GITHUB_OWNER, login=result.get("login") or "", auth="device")
    return result
