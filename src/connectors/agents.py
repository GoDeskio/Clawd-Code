"""OpenAI-compatible agent endpoints the user already runs.

No invented agents. Cursor / Codex / local hooks are documented in hooks.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from src.providers.local_endpoints import RemoteEndpointError, assert_local_or_lan_url

from .httputil import ConnectorHttpError, request_json
from .store import read_connectors


def _normalize_base(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        raise ValueError("agent base URL is required")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("agent URL must be http or https")
    return raw


def assert_agent_url(url: str, *, allow_remote: bool = False) -> str:
    raw = _normalize_base(url)
    host = urlparse(raw).hostname or ""
    if allow_remote:
        return raw
    try:
        return assert_local_or_lan_url(raw)
    except RemoteEndpointError:
        # User-pasted HTTPS agent endpoints (their own) are allowed; we do not auto-discover them.
        if urlparse(raw).scheme == "https" and host:
            return raw
        raise


def test_agent_endpoint(base_url: str, api_key: str = "", *, allow_remote: bool = False) -> dict[str, Any]:
    url = assert_agent_url(base_url, allow_remote=allow_remote)
    token = (api_key or "").strip() or None
    last_error = ""
    for path in ("/models", "/v1/models", "/health", ""):
        target = url if not path else f"{url}{path}" if not url.endswith(path) else url
        try:
            payload = request_json(target, token=token, timeout=8)
            models: list[str] = []
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                models = [str(item.get("id")) for item in payload["data"] if isinstance(item, dict) and item.get("id")]
            return {"ok": True, "base_url": url, "models": models, "probe": target}
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
    raise ConnectorHttpError(last_error or f"could not reach {url}")


def list_agent_tools(base_url: str, api_key: str = "") -> list[dict[str, str]]:
    url = assert_agent_url(base_url, allow_remote=True)
    token = (api_key or "").strip() or None
    for path in ("/tools", "/v1/tools"):
        try:
            payload = request_json(f"{url}{path}", token=token, timeout=8)
        except Exception:
            continue
        rows: list[dict[str, str]] = []
        items = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and (item.get("name") or item.get("id")):
                    rows.append({
                        "name": str(item.get("name") or item.get("id")),
                        "description": str(item.get("description") or ""),
                    })
        if rows:
            return rows
    return []


def invoke_agent(
    base_url: str,
    prompt: str,
    *,
    api_key: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    url = assert_agent_url(base_url, allow_remote=True)
    token = (api_key or "").strip() or None
    body = {
        "model": model or "default",
        "messages": [{"role": "user", "content": prompt}],
    }
    last_error = ""
    for path in ("/chat/completions", "/v1/chat/completions"):
        try:
            payload = request_json(f"{url}{path}", method="POST", token=token, body=body, timeout=60)
            if isinstance(payload, dict):
                choices = payload.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message") or {}
                    text = message.get("content") if isinstance(message, dict) else ""
                    return {"ok": True, "text": text or "", "raw_keys": list(payload.keys())}
            return {"ok": True, "payload": payload}
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
    raise ConnectorHttpError(last_error or "agent invoke failed")


def get_saved_agent(name_or_id: str) -> dict[str, Any]:
    for item in read_connectors().get("agents") or []:
        if item.get("id") == name_or_id or item.get("name") == name_or_id:
            return item
    raise ValueError(f"unknown agent: {name_or_id}")
