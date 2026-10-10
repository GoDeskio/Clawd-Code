"""Per-user registry of MQTT, Home Assistant, HTTP, and SSH devices."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from src.agent.memory import current_user_id
from src.devices.control import KIND_IDS, safe_device_view
from src.devices.lan import require_private_host
from src.secret_store import has_secret, put_secret


def devices_root(directory: Path | None = None) -> Path:
    if directory is not None:
        path = directory
    else:
        raw = os.environ.get("JONATHAN_DEVICES_DIR", "").strip()
        path = Path(raw) if raw else Path.home() / ".clawd" / "devices"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _path(directory: Path | None, user_id: str | None) -> Path:
    user = user_id or current_user_id()
    return devices_root(directory) / f"devices-{user}.json"


def _actions(value: object) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,\n]+", value)
    elif isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        raise ValueError("actions must be a list")
    found: list[str] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        if any(char in text for char in "\r\x00"):
            raise ValueError("action is not valid")
        if text not in found:
            found.append(text)
    return found


def _port(value: object, kind: str) -> int:
    defaults = {"mqtt": 1883, "homeassistant": 8123, "http": 80, "ssh": 22}
    if value in (None, ""):
        return defaults[kind]
    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("device port is not valid")
    return port


def load_devices(directory: Path | None = None, *, user_id: str | None = None) -> list[dict]:
    path = _path(directory, user_id)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = raw.get("devices") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return []
    found: list[dict] = []
    for item in rows:
        if isinstance(item, dict) and item.get("id"):
            found.append(item)
    return found


def _write(devices: list[dict], directory: Path | None, user_id: str) -> None:
    path = _path(directory, user_id)
    public = []
    for device in devices:
        public.append(
            {
                "id": device["id"],
                "kind": device["kind"],
                "host": device["host"],
                "port": device["port"],
                "user": device.get("user") or "",
                "actions": list(device.get("actions") or []),
            }
        )
    path.write_text(json.dumps({"devices": public}, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        return


def public_devices(
    directory: Path | None = None,
    *,
    user_id: str | None = None,
    backend: object | None = None,
) -> dict[str, object]:
    user = user_id or current_user_id()
    root = devices_root(directory)
    devices = []
    for device in load_devices(root, user_id=user):
        row = safe_device_view(device)
        row["secret_set"] = has_secret(root, user, f"device-{device['id']}", backend=backend)
        devices.append(row)
    return {"devices": devices}


def update_devices(
    changes: object,
    directory: Path | None = None,
    *,
    user_id: str | None = None,
    backend: object | None = None,
) -> dict[str, object]:
    rows = changes
    if isinstance(changes, dict):
        rows = changes.get("devices", [changes] if changes.get("id") or changes.get("host") else [])
    if not isinstance(rows, list):
        raise ValueError("devices must be a list")
    user = user_id or current_user_id()
    root = devices_root(directory)
    devices = load_devices(root, user_id=user)
    by_id = {str(item["id"]): item for item in devices}
    meaningful = False
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("each device must be an object")
        device_id = str(item.get("id") or "").strip()
        if not device_id:
            continue
        if any(char in device_id for char in "\n\r\x00/\\ "):
            raise ValueError("device id is not valid")
        meaningful = True
        if item.get("delete"):
            by_id.pop(device_id, None)
            continue
        kind = str(item.get("kind") or (by_id.get(device_id) or {}).get("kind") or "").strip()
        if kind not in KIND_IDS:
            raise ValueError(f"unknown device kind: {kind}")
        current = by_id.get(device_id, {})
        host = require_private_host(str(item.get("host") or current.get("host") or ""))
        record = {
            "id": device_id,
            "kind": kind,
            "host": host,
            "port": _port(item.get("port", current.get("port")), kind),
            "user": str(item.get("user") if "user" in item else current.get("user") or "").strip(),
            "actions": _actions(item.get("actions", current.get("actions") or [])),
        }
        secret = item.get("secret")
        if isinstance(secret, str) and secret.strip():
            put_secret(root, user, f"device-{device_id}", secret, backend=backend)
        by_id[device_id] = record
    if meaningful:
        _write(list(by_id.values()), root, user)
    return public_devices(root, user_id=user, backend=backend)


def get_device(device_id: str, directory: Path | None = None, *, user_id: str | None = None) -> dict:
    for device in load_devices(directory, user_id=user_id):
        if str(device.get("id")) == device_id:
            return device
    raise ValueError(f"unknown device: {device_id}")
