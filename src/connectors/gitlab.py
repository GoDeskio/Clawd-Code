"""GitLab connector. Same capabilities and branch rules as GitHub."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from .git_common import clone_repo, pull_repo, push_branch, workspace_git_status
from .httputil import request_json
from .store import DEFAULT_GITLAB_HOST, read_connectors, save_forge_login


class GitLabConnector:
    def __init__(self, token: str | None = None, host: str | None = None, owner: str | None = None) -> None:
        data = read_connectors()["gitlab"]
        self.token = (token if token is not None else data.get("token") or "").strip()
        self.host = (host if host is not None else data.get("host") or DEFAULT_GITLAB_HOST).rstrip("/")
        self.owner = (owner if owner is not None else data.get("owner") or "").strip()

    def require_token(self) -> str:
        if not self.token:
            raise ValueError("GitLab is not connected. Paste a personal access token in settings.")
        return self.token

    def _api(self, path: str, *, method: str = "GET", body: Any = None) -> Any:
        return request_json(
            f"{self.host}/api/v4{path}",
            method=method,
            token=self.require_token(),
            extra_auth_header=("PRIVATE-TOKEN", self.require_token()),
            body=body,
        )

    def login_with_token(self, token: str, owner: str | None = None, host: str | None = None) -> dict[str, Any]:
        self.token = token.strip()
        if host:
            self.host = host.rstrip("/")
        me = self.whoami()
        username = str(me.get("username") or "")
        save_forge_login(
            "gitlab",
            token=self.token,
            owner=owner if owner is not None else (self.owner or username),
            login=username,
            auth="token",
            forge_host=self.host,
        )
        return {"ok": True, "login": username, "owner": owner or self.owner or username, "host": self.host}

    def whoami(self) -> dict[str, Any]:
        return self._api("/user")

    def list_projects(self, owner: str | None = None) -> list[dict[str, Any]]:
        target = (owner or self.owner or "").strip()
        path = "/projects?membership=true&simple=true&order_by=updated_at&per_page=50"
        if target:
            path = f"/groups/{quote(target, safe='')}/projects?simple=true&per_page=50"
        try:
            payload = self._api(path)
        except Exception:
            payload = self._api("/projects?membership=true&simple=true&order_by=updated_at&per_page=50")
        rows = payload if isinstance(payload, list) else []
        return [
            {
                "full_name": item.get("path_with_namespace"),
                "clone_url": item.get("http_url_to_repo"),
                "default_branch": item.get("default_branch") or "main",
                "html_url": item.get("web_url"),
                "id": item.get("id"),
            }
            for item in rows
            if isinstance(item, dict)
        ]

    def create_project(self, name: str, *, owner: str | None = None, visibility: str = "private") -> dict[str, Any]:
        target = (owner or self.owner or "").strip()
        body: dict[str, Any] = {"name": name, "visibility": visibility}
        if target:
            # namespace_id lookup
            try:
                group = self._api(f"/groups/{quote(target, safe='')}")
                if isinstance(group, dict) and group.get("id"):
                    body["namespace_id"] = group["id"]
            except Exception:
                pass
        created = self._api("/projects", method="POST", body=body)
        return {
            "full_name": created.get("path_with_namespace"),
            "clone_url": created.get("http_url_to_repo"),
            "html_url": created.get("web_url"),
            "default_branch": created.get("default_branch") or "main",
            "id": created.get("id"),
            "owner": target,
        }

    def clone(self, project: str, dest: str | Path) -> dict[str, Any]:
        if project.startswith("http"):
            url = project
        else:
            url = f"{self.host}/{project}.git"
        path = clone_repo(
            url,
            Path(dest),
            token=self.require_token(),
            extra_header=f"PRIVATE-TOKEN: {self.require_token()}",
        )
        return {"ok": True, "path": str(path), "url": url}

    def pull(self, dest: str | Path) -> dict[str, Any]:
        return pull_repo(
            Path(dest),
            token=self.require_token(),
            extra_header=f"PRIVATE-TOKEN: {self.require_token()}",
        )

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
            extra_header=f"PRIVATE-TOKEN: {self.require_token()}",
            default=default_branch,
            operator_named=operator_named,
        )

    def create_merge_request(
        self,
        project: str,
        *,
        title: str,
        source: str,
        target: str | None = None,
        body: str = "",
    ) -> dict[str, Any]:
        encoded = quote(project, safe="")
        info = self._api(f"/projects/{encoded}")
        default = target or info.get("default_branch") or "main"
        if source == default:
            raise ValueError("Open a merge request from a feature branch, not from the default branch.")
        mr = self._api(
            f"/projects/{encoded}/merge_requests",
            method="POST",
            body={"title": title, "source_branch": source, "target_branch": default, "description": body},
        )
        return {
            "iid": mr.get("iid"),
            "html_url": mr.get("web_url"),
            "head": source,
            "base": default,
        }

    def status(self, path: str | Path) -> dict[str, Any]:
        return workspace_git_status(Path(path))


def start_gitlab_device_login(application_id: str, host: str = DEFAULT_GITLAB_HOST) -> dict[str, Any]:
    app = (application_id or "").strip()
    if not app:
        raise ValueError(
            "Device login needs a GitLab application ID. "
            "Create one under GitLab → Applications, or paste a personal access token instead."
        )
    from urllib.request import Request, urlopen
    import json

    root = (host or DEFAULT_GITLAB_HOST).rstrip("/")
    req = Request(
        f"{root}/oauth/authorize_device",
        data=urlencode({"client_id": app, "scope": "api"}).encode(),
        headers={"Accept": "application/json", "User-Agent": "JonathanAi/0.1"},
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(payload.get("error_description") or payload["error"])
    return {
        "device_code": payload.get("device_code"),
        "user_code": payload.get("user_code"),
        "verification_uri": payload.get("verification_uri") or f"{root}/-/profile/device",
        "interval": int(payload.get("interval") or 5),
        "expires_in": int(payload.get("expires_in") or 900),
        "client_id": app,
        "host": root,
        "message": f"Open {payload.get('verification_uri')} and enter {payload.get('user_code')}",
    }


def poll_gitlab_device_login(application_id: str, device_code: str, host: str = DEFAULT_GITLAB_HOST) -> dict[str, Any]:
    from urllib.request import Request, urlopen
    import json

    root = (host or DEFAULT_GITLAB_HOST).rstrip("/")
    req = Request(
        f"{root}/oauth/token",
        data=urlencode({
            "client_id": application_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode(),
        headers={"Accept": "application/json", "User-Agent": "JonathanAi/0.1"},
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("error") in {"authorization_pending", "slow_down"}:
        return {"pending": True}
    if payload.get("error"):
        raise RuntimeError(payload.get("error_description") or payload["error"])
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("GitLab device login did not return a token")
    return GitLabConnector(host=root).login_with_token(token, host=root)
