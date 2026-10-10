"""HTTP calls for the three official bot APIs. The token is not logged."""

from __future__ import annotations

import json
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.secret_mask import mask_secrets

OFFICIAL_HOSTS = {
    "telegram": "api.telegram.org",
    "discord": "discord.com",
    "slack": "slack.com",
}

Transport = Callable[[str, str, dict[str, str], dict], object]


def official_url(channel: str, url: str) -> str:
    expected = OFFICIAL_HOSTS.get(channel)
    host = (urlparse(url).hostname or "").lower()
    if expected is None or host != expected:
        raise ValueError(f"refusing unofficial {channel} host")
    return url


def urllib_transport(method: str, url: str, headers: dict[str, str], payload: dict) -> object:
    """POST JSON and return the decoded body. The URL is not logged."""
    channel = _channel_for_url(url)
    official_url(channel, url)
    req_headers = {"Content-Type": "application/json", "User-Agent": "jonathan-ai"}
    req_headers.update(headers)
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(mask_secrets(f"{channel} request failed: {exc}")) from None
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{channel} returned a response that was not JSON") from exc


def _channel_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for channel, expected in OFFICIAL_HOSTS.items():
        if host == expected:
            return channel
    raise ValueError("refusing unofficial channel host")
