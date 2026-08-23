"""Small HTTP JSON helper. Tokens are never logged."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ConnectorHttpError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def request_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    headers: dict[str, str] | None = None,
    body: Any = None,
    timeout: float = 20.0,
    auth_scheme: str = "Bearer",
    extra_auth_header: tuple[str, str] | None = None,
) -> Any:
    hdrs = {
        "Accept": "application/json",
        "User-Agent": "JonathanAi/0.1 (GoDeskio/Clawd-Code)",
        **(headers or {}),
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    key = (token or "").strip()
    if key:
        hdrs["Authorization"] = f"{auth_scheme} {key}"
    if extra_auth_header:
        hdrs[extra_auth_header[0]] = extra_auth_header[1]
    req = Request(url, data=data, headers=hdrs, method=method.upper())
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        status = int(exc.code)
        detail = raw.decode("utf-8", errors="replace")[:400]
        raise ConnectorHttpError(f"{method} {url.split('?')[0]} failed ({status}): {detail}", status=status) from exc
    except URLError as exc:
        raise ConnectorHttpError(str(exc.reason or exc)) from exc
    if not raw:
        return {"ok": True, "status": status}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": status < 400, "text": raw.decode("utf-8", errors="replace"), "status": status}
