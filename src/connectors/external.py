"""Generic external-service connectors with explicit credential and OAuth flows."""

from __future__ import annotations

import base64
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .store import read_connectors, save_external_service


def _service(service_id: str) -> dict[str, Any]:
    for item in read_connectors().get("services") or []:
        if item.get("id") == service_id or item.get("name") == service_id:
            return dict(item)
    raise ValueError(f"unknown external service: {service_id}")


def _http_url(value: str, label: str) -> str:
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{label} must be an http(s) URL without embedded credentials")
    return url


def authorization_request(service_id: str, *, redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob") -> dict[str, str]:
    item = _service(service_id)
    if item.get("auth_type") != "oauth2":
        raise ValueError("service is not configured for OAuth 2.0")
    authorization_url = _http_url(str(item.get("authorization_url") or ""), "authorization URL")
    client_id = str(item.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("OAuth client ID is required")
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": str(item.get("scopes") or ""),
        "state": state,
    })
    return {"authorization_url": authorization_url + ("&" if "?" in authorization_url else "?") + query,
            "state": state, "redirect_uri": redirect_uri}


def exchange_authorization_code(
    service_id: str,
    code: str,
    *,
    redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob",
) -> dict[str, Any]:
    item = _service(service_id)
    token_url = _http_url(str(item.get("token_url") or ""), "token URL")
    if not str(code or "").strip():
        raise ValueError("authorization code is required")
    form = {
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": redirect_uri,
        "client_id": str(item.get("client_id") or ""),
        "client_secret": str(item.get("client_secret") or ""),
    }
    request = urllib.request.Request(
        token_url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise ValueError(f"OAuth token exchange failed ({exc.code}): {detail}") from exc
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise ValueError("OAuth provider returned no access token")
    save_external_service(
        name=str(item.get("name") or "External service"),
        base_url=str(item.get("base_url") or ""),
        auth_type="oauth2",
        service_id=str(item.get("id") or service_id),
        **{key: item.get(key) or "" for key in (
            "username", "password", "api_key", "api_key_header", "bearer_token",
            "authorization_url", "token_url", "client_id", "client_secret", "scopes",
        )},
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or item.get("refresh_token") or ""),
    )
    return {"connected": True, "token_type": payload.get("token_type") or "Bearer",
            "scope": payload.get("scope") or item.get("scopes") or ""}


def test_service(service_id: str) -> dict[str, Any]:
    item = _service(service_id)
    url = _http_url(str(item.get("base_url") or ""), "service URL")
    headers = {"Accept": "application/json, text/plain, */*", "User-Agent": "JonathanAi/0.3"}
    auth_type = str(item.get("auth_type") or "none")
    if auth_type in {"basic", "password"}:
        token = base64.b64encode(f"{item.get('username') or ''}:{item.get('password') or ''}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    elif auth_type == "api_key":
        headers[str(item.get("api_key_header") or "X-API-Key")] = str(item.get("api_key") or "")
    elif auth_type == "bearer":
        headers["Authorization"] = f"Bearer {item.get('bearer_token') or ''}"
    elif auth_type == "oauth2":
        headers["Authorization"] = f"Bearer {item.get('access_token') or ''}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            return {"reachable": True, "status": response.status, "content_type": response.headers.get("Content-Type", ""), "preview": body}
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        return {"reachable": False, "status": exc.code, "preview": body}

