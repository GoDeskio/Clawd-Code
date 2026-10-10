"""Run one allow-listed action on a registered LAN device.

MQTT, Home Assistant REST, generic HTTP, and SSH are the only controls.
The host is checked again here so a hand-edited settings file cannot point
at the WAN. Secrets are read from the store and are not included in results.
"""

from __future__ import annotations

import json
import shlex
from typing import Callable
from urllib.request import Request, urlopen

from src.devices.lan import WanTargetError, require_private_host, require_private_url
from src.secret_mask import mask_secrets
from src.secret_store import get_secret

KIND_IDS = ("mqtt", "homeassistant", "http", "ssh")
Runner = Callable[[list[str]], str]
Poster = Callable[[str, str, dict[str, str], bytes], str]


def approval_key(device_id: str, action: str) -> str:
    return f"device:{device_id}:{action}"


def _origin(host: str, port: int, scheme: str = "http") -> str:
    cleaned = require_private_host(host)
    pretty = f"[{cleaned}]" if ":" in cleaned else cleaned
    return require_private_url(f"{scheme}://{pretty}:{int(port)}")


def _mqtt_packet(topic: str, payload: str, username: str, password: str) -> bytes:
    def enc(text: str) -> bytes:
        raw = text.encode("utf-8")
        return len(raw).to_bytes(2, "big") + raw

    def frame(header: int, body: bytes) -> bytes:
        size = len(body)
        length = bytearray()
        while True:
            digit = size % 128
            size //= 128
            if size:
                digit |= 0x80
            length.append(digit)
            if not size:
                break
        return bytes([header]) + bytes(length) + body

    flags = 0x02
    body = enc("jonathan-ai")
    if username:
        flags |= 0x80
        body += enc(username)
        if password:
            flags |= 0x40
            body += enc(password)
    variable = enc("MQTT") + bytes([4, flags, 0, 60])
    connect = frame(0x10, variable + body)
    publish = frame(0x30, enc(topic) + payload.encode("utf-8"))
    return connect + publish


def _default_poster(method: str, url: str, headers: dict[str, str], body: bytes) -> str:
    require_private_url(url)
    request = Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=8) as response:
            return response.read(8000).decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(mask_secrets(f"device request failed: {exc}")) from None


def _default_tcp(host: str, port: int, packet: bytes) -> None:
    import socket

    require_private_host(host)
    sock = socket.create_connection((host, int(port)), timeout=5)
    try:
        sock.sendall(packet)
    finally:
        sock.close()


def _default_ssh(argv: list[str]) -> str:
    import subprocess

    completed = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
    output = (completed.stdout or "") + (completed.stderr or "")
    return mask_secrets(output.strip()) or f"exit {completed.returncode}"


def perform_action(
    device: dict,
    action: str,
    *,
    directory,
    user_id: str,
    backend: object | None = None,
    poster: Poster | None = None,
    tcp_send: Callable[[str, int, bytes], None] | None = None,
    ssh_runner: Runner | None = None,
) -> str:
    kind = str(device.get("kind") or "")
    if kind not in KIND_IDS:
        raise ValueError(f"unknown device kind: {kind}")
    name = str(action or "").strip()
    allowed = list(device.get("actions") or [])
    if name not in allowed:
        raise ValueError(f"action {name!r} is not on the allow-list for {device.get('id')}")
    host = require_private_host(str(device.get("host") or ""))
    port = int(device.get("port") or 0)
    from src.devices.registry import devices_root

    root = devices_root(directory)
    secret = get_secret(root, user_id, f"device-{device.get('id')}", backend=backend)
    http = poster or _default_poster
    if kind == "mqtt":
        if any(char in name for char in "\n\r\x00#"):
            raise ValueError("mqtt topic is not allowed")
        packet = _mqtt_packet(name, name, str(device.get("user") or ""), secret)
        (tcp_send or _default_tcp)(host, port or 1883, packet)
        return f"MQTT publish {name} to {host}"
    if kind == "homeassistant":
        if name.count(".") != 1:
            raise ValueError("home assistant action must look like domain.service")
        domain, service = name.split(".", 1)
        origin = _origin(host, port or 8123)
        url = f"{origin}/api/services/{domain}/{service}"
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        body = http("POST", url, headers, b"{}")
        return mask_secrets(f"Home Assistant {name} at {host}\n{body}".strip())
    if kind == "http":
        if name.startswith("/") is False:
            name = "/" + name
        if ".." in name or "\\" in name or "://" in name:
            raise ValueError("http action path is not allowed")
        origin = _origin(host, port or 80)
        body = http("POST", origin + name, {"Content-Type": "application/json"}, b"{}")
        return mask_secrets(f"HTTP {name} at {host}\n{body}".strip())
    user = str(device.get("user") or "").strip()
    if not user or any(char in user for char in " \n\r\x00@"):
        raise ValueError("ssh user is required")
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(port or 22),
        f"{user}@{host}",
        name,
    ]
    output = (ssh_runner or _default_ssh)(argv)
    return mask_secrets(f"SSH {user}@{host}\n{shlex.join(argv)}\n{output}".strip())


def safe_device_view(device: dict) -> dict:
    """Public device row. The secret is not included."""
    return {
        "id": device.get("id"),
        "kind": device.get("kind"),
        "host": device.get("host"),
        "port": device.get("port"),
        "user": device.get("user") or "",
        "actions": list(device.get("actions") or []),
    }


def dumps_result(text: str) -> str:
    return json.dumps({"text": mask_secrets(text)})
