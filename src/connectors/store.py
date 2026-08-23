"""Persist connector credentials on this machine only."""

from __future__ import annotations

import uuid
from typing import Any

from src.config import load_config, save_config

DEFAULT_GITHUB_OWNER = "GoDeskio"
DEFAULT_GITLAB_HOST = "https://gitlab.com"

SECRET_FORGE_FIELDS = ("token",)
SECRET_ITEM_FIELDS = ("token", "api_key")


def _empty_connectors() -> dict[str, Any]:
    return {
        "github": {"token": "", "owner": DEFAULT_GITHUB_OWNER, "login": "", "auth": ""},
        "gitlab": {"token": "", "owner": "", "host": DEFAULT_GITLAB_HOST, "login": "", "auth": ""},
        "mcp": [],
        "agents": [],
    }


def read_connectors() -> dict[str, Any]:
    config = load_config()
    raw = config.get("connectors")
    base = _empty_connectors()
    if not isinstance(raw, dict):
        return base
    for name in ("github", "gitlab"):
        item = raw.get(name)
        if isinstance(item, dict):
            base[name].update({k: item.get(k, base[name].get(k, "")) for k in base[name]})
    for key in ("mcp", "agents"):
        items = raw.get(key)
        if isinstance(items, list):
            base[key] = [item for item in items if isinstance(item, dict)]
    return base


def write_connectors(connectors: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    config["connectors"] = connectors
    save_config(config)
    return public_connectors(connectors)


def _mask(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) > 12:
        return f"{text[:4]}…{text[-4:]}"
    return "••••"


def public_connectors(connectors: dict[str, Any] | None = None) -> dict[str, Any]:
    data = connectors or read_connectors()
    github = dict(data.get("github") or {})
    gitlab = dict(data.get("gitlab") or {})
    return {
        "github": {
            "configured": bool(str(github.get("token") or "").strip()),
            "owner": github.get("owner") or DEFAULT_GITHUB_OWNER,
            "login": github.get("login") or "",
            "auth": github.get("auth") or "",
            "token_masked": _mask(str(github.get("token") or "")),
        },
        "gitlab": {
            "configured": bool(str(gitlab.get("token") or "").strip()),
            "owner": gitlab.get("owner") or "",
            "host": gitlab.get("host") or DEFAULT_GITLAB_HOST,
            "login": gitlab.get("login") or "",
            "auth": gitlab.get("auth") or "",
            "token_masked": _mask(str(gitlab.get("token") or "")),
        },
        "mcp": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "transport": item.get("transport") or ("stdio" if item.get("command") else "http"),
                "command": item.get("command") or "",
                "url": item.get("url") or "",
                "enabled": bool(item.get("enabled", True)),
                "configured": bool(item.get("command") or item.get("url")),
                "has_token": bool(str(item.get("token") or "").strip()),
            }
            for item in data.get("mcp") or []
            if isinstance(item, dict)
        ],
        "agents": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "base_url": item.get("base_url") or "",
                "enabled": bool(item.get("enabled", True)),
                "kind": item.get("kind") or "openai-compatible",
                "has_token": bool(str(item.get("api_key") or "").strip()),
            }
            for item in data.get("agents") or []
            if isinstance(item, dict)
        ],
        "hooks": {
            "cursor": "Drop ~/.clawd/hooks/cursor.json or add an OpenAI-compatible agent URL.",
            "codex": "Same JSON hook, or POST http://127.0.0.1:8765/api/hooks/inbound with the desktop token.",
            "inbound": "/api/hooks/inbound",
        },
    }


def save_forge_login(
    host: str,
    *,
    token: str,
    owner: str | None = None,
    login: str = "",
    auth: str = "token",
    forge_host: str | None = None,
) -> dict[str, Any]:
    if host not in {"github", "gitlab"}:
        raise ValueError("host must be github or gitlab")
    if not str(token or "").strip():
        raise ValueError(f"{host} token cannot be empty")
    data = read_connectors()
    slot = data[host]
    slot["token"] = token.strip()
    slot["auth"] = auth
    if login:
        slot["login"] = login
    if owner is not None:
        slot["owner"] = owner.strip() or (DEFAULT_GITHUB_OWNER if host == "github" else "")
    elif host == "github" and not slot.get("owner"):
        slot["owner"] = DEFAULT_GITHUB_OWNER
    if host == "gitlab" and forge_host:
        slot["host"] = str(forge_host).rstrip("/")
    return write_connectors(data)


def save_mcp_server(
    *,
    name: str,
    command: str = "",
    args: list[str] | None = None,
    url: str = "",
    token: str = "",
    enabled: bool = True,
    server_id: str | None = None,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("MCP server name is required")
    if not command.strip() and not url.strip():
        raise ValueError("Provide a stdio command or an HTTP MCP URL")
    data = read_connectors()
    item = {
        "id": server_id or uuid.uuid4().hex[:12],
        "name": name.strip(),
        "command": command.strip(),
        "args": list(args or []),
        "url": url.strip(),
        "token": token.strip(),
        "enabled": bool(enabled),
        "transport": "stdio" if command.strip() else "http",
    }
    servers = data["mcp"]
    for index, existing in enumerate(servers):
        if existing.get("id") == item["id"] or existing.get("name") == item["name"]:
            if not item["token"]:
                item["token"] = existing.get("token") or ""
            servers[index] = item
            break
    else:
        servers.append(item)
    return write_connectors(data)


def set_mcp_enabled(server_id: str, enabled: bool) -> dict[str, Any]:
    data = read_connectors()
    for item in data["mcp"]:
        if item.get("id") == server_id or item.get("name") == server_id:
            item["enabled"] = bool(enabled)
            break
    else:
        raise ValueError(f"unknown MCP server: {server_id}")
    return write_connectors(data)


def set_agent_enabled(agent_id: str, enabled: bool) -> dict[str, Any]:
    data = read_connectors()
    for item in data["agents"]:
        if item.get("id") == agent_id or item.get("name") == agent_id:
            item["enabled"] = bool(enabled)
            break
    else:
        raise ValueError(f"unknown agent: {agent_id}")
    return write_connectors(data)


def save_agent(
    *,
    name: str,
    base_url: str,
    api_key: str = "",
    kind: str = "openai-compatible",
    enabled: bool = True,
    agent_id: str | None = None,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("agent name is required")
    if not base_url.strip():
        raise ValueError("agent base URL is required")
    data = read_connectors()
    item = {
        "id": agent_id or uuid.uuid4().hex[:12],
        "name": name.strip(),
        "base_url": base_url.strip().rstrip("/"),
        "api_key": api_key.strip(),
        "kind": kind,
        "enabled": bool(enabled),
    }
    agents = data["agents"]
    for index, existing in enumerate(agents):
        if existing.get("id") == item["id"] or existing.get("name") == item["name"]:
            if not item["api_key"]:
                item["api_key"] = existing.get("api_key") or ""
            agents[index] = item
            break
    else:
        agents.append(item)
    return write_connectors(data)
