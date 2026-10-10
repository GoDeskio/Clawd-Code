"""Accept only loopback, private, and link-local device addresses.

This reuses the local-LLM LAN check. Public and WAN hosts are refused before
any socket is opened.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from src.providers.local_endpoints import _host_is_loopback_or_lan


class WanTargetError(ValueError):
    """The device address is not on the local network."""


def require_private_host(host: str) -> str:
    """Return a cleaned host, or refuse a WAN target."""
    text = (host or "").strip().strip("[]")
    if not text or any(char in text for char in "\n\r\x00 /\\@"):
        raise WanTargetError("device host is not valid")
    if not _host_is_loopback_or_lan(text):
        raise WanTargetError(f"refusing WAN host {text}; device control stays on the LAN")
    return text


def require_private_url(url: str) -> str:
    raw = (url or "").strip()
    if "@" in raw:
        raise WanTargetError("device URL cannot carry user info")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise WanTargetError("device URL must be http or https")
    if not parsed.hostname:
        raise WanTargetError("device URL is missing a host")
    require_private_host(parsed.hostname)
    return raw


def host_is_private_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip("[]"))
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
