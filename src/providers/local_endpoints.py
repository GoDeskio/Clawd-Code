"""Discover OpenAI-compatible local LLM servers on loopback/LAN only.

Never contacts Hugging Face or any public WAN host. Custom URLs are rejected
unless the hostname resolves only to loopback or private LAN addresses.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ProbeFn = Callable[[str, float, dict[str, str] | None], tuple[int, Any]]

LOCAL_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "ollama",
        "label": "Ollama",
        "urls": ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434"),
        "default_url": "http://127.0.0.1:11434/v1",
    },
    {
        "id": "lmstudio",
        "label": "LM Studio",
        "urls": ("http://127.0.0.1:1234/v1",),
        "default_url": "http://127.0.0.1:1234/v1",
    },
    {
        "id": "vllm",
        "label": "vLLM",
        "urls": ("http://127.0.0.1:8000/v1",),
        "default_url": "http://127.0.0.1:8000/v1",
    },
    {
        "id": "llamacpp",
        "label": "llama.cpp server",
        "urls": ("http://127.0.0.1:8080/v1",),
        "default_url": "http://127.0.0.1:8080/v1",
    },
    {
        "id": "tgi",
        "label": "Hugging Face TGI",
        "urls": ("http://127.0.0.1:3000/v1", "http://127.0.0.1:8080"),
        "default_url": "http://127.0.0.1:3000/v1",
    },
)


class RemoteEndpointError(ValueError):
    """Raised when a URL is not loopback/LAN."""


def _host_is_loopback_or_lan(host: str) -> bool:
    raw = (host or "").strip().strip("[]")
    if not raw:
        return False
    lowered = raw.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(raw)
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(raw, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return True


def assert_local_or_lan_url(url: str) -> str:
    """Accept only http(s) URLs whose host is loopback or RFC1918/LAN."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteEndpointError("local endpoints must be http or https")
    if not parsed.hostname:
        raise RemoteEndpointError("local endpoint is missing a host")
    if not _host_is_loopback_or_lan(parsed.hostname):
        raise RemoteEndpointError(
            f"refusing WAN host {parsed.hostname!r}; local LLMs stay on loopback/LAN"
        )
    return raw.rstrip("/")


def normalize_openai_base(url: str) -> str:
    raw = assert_local_or_lan_url(url)
    if raw.endswith("/v1"):
        return raw
    return f"{raw}/v1"


def http_json(
    url: str,
    *,
    timeout: float = 0.8,
    headers: dict[str, str] | None = None,
    allow_wan: bool = False,
) -> tuple[int, Any]:
    if not allow_wan:
        assert_local_or_lan_url(url)
    req = Request(url, headers={"Accept": "application/json", **(headers or {})}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        status = int(exc.code)
    except URLError as exc:
        raise ConnectionError(str(exc.reason or exc)) from exc
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", errors="replace")


def _auth_headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key or key == "local":
        return {}
    return {"Authorization": f"Bearer {key}"}


def _model_ids(payload: Any) -> list[str]:
    names: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    names.append(str(item["id"]))
        models = payload.get("models")
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("model") or item.get("id")
                    if name:
                        names.append(str(name))
                elif isinstance(item, str):
                    names.append(item)
        model_id = payload.get("model_id") or payload.get("model")
        if isinstance(model_id, str) and model_id:
            names.append(model_id)
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def list_local_models(
    base_url: str,
    api_key: str | None = None,
    *,
    timeout: float = 1.5,
    probe: ProbeFn | None = None,
) -> list[str]:
    """List models from an OpenAI-compatible or Ollama local server."""
    root = assert_local_or_lan_url(base_url)
    do_probe = probe or (lambda url, t, headers: http_json(url, timeout=t, headers=headers))
    headers = _auth_headers(api_key)
    candidates = []
    if root.endswith("/v1"):
        candidates.append(f"{root}/models")
        candidates.append(f"{root[:-3]}/api/tags")
        candidates.append(f"{root[:-3]}/info")
    else:
        candidates.append(f"{root}/v1/models")
        candidates.append(f"{root}/api/tags")
        candidates.append(f"{root}/info")
        candidates.append(f"{root}/models")
    last_error = ""
    for url in candidates:
        try:
            status, payload = do_probe(url, timeout, headers)
        except Exception as exc:  # noqa: BLE001 — probe next candidate
            last_error = str(exc)
            continue
        if status >= 400:
            last_error = f"{url} -> {status}"
            continue
        names = _model_ids(payload)
        if names:
            return names
    if last_error:
        raise ConnectionError(last_error)
    return []


def _probe_preset(
    preset: dict[str, Any],
    probe: ProbeFn,
    timeout: float,
) -> dict[str, Any] | None:
    last_error = ""
    for url in preset["urls"]:
        try:
            models = list_local_models(url, probe=probe, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        return {
            "id": preset["id"],
            "label": preset["label"],
            "base_url": normalize_openai_base(preset.get("default_url") or url),
            "reachable": True,
            "models": models,
        }
    return {
        "id": preset["id"],
        "label": preset["label"],
        "base_url": preset["default_url"],
        "reachable": False,
        "models": [],
        "error": last_error,
    }


def scan_local_endpoints(
    extra_urls: list[str] | None = None,
    *,
    timeout: float = 0.6,
    probe: ProbeFn | None = None,
) -> list[dict[str, Any]]:
    """Scan well-known local ports. Does not contact Hugging Face or the WAN."""
    do_probe = probe or (lambda url, t, headers: http_json(url, timeout=t, headers=headers))
    found: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_probe_preset, preset, do_probe, timeout): preset["id"]
            for preset in LOCAL_PRESETS
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                found.append(result)
    order = {item["id"]: index for index, item in enumerate(LOCAL_PRESETS)}
    found.sort(key=lambda item: order.get(item["id"], 99))

    for raw in extra_urls or []:
        url = assert_local_or_lan_url(raw)
        try:
            models = list_local_models(url, probe=do_probe, timeout=timeout)
            found.append({
                "id": "custom",
                "label": "Custom",
                "base_url": normalize_openai_base(url),
                "reachable": True,
                "models": models,
            })
        except Exception as exc:  # noqa: BLE001
            found.append({
                "id": "custom",
                "label": "Custom",
                "base_url": url,
                "reachable": False,
                "models": [],
                "error": str(exc),
            })
    return found
