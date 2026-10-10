"""Commands for LAN discovery and registered device control."""

from __future__ import annotations

from pathlib import Path

from src.devices.discover import discover_from_sources, probe_mdns, probe_ssdp, read_arp_text
from src.devices.registry import get_device, public_devices
from src.secret_mask import mask_secrets

_USAGE = (
    "Usage: /devices list | /devices discover [probe] | /devices do <id> <action>\n"
    "Discovery reads the ARP table. probe also sends one mDNS query and one SSDP search.\n"
    "Control stays on private and link-local addresses, and each action must be allow-listed."
)


def format_devices_command(
    args: str,
    *,
    directory: Path | None = None,
    user_id: str | None = None,
    arp_text: str | None = None,
    probe: bool | None = None,
) -> str:
    parts = args.split()
    action = parts[0] if parts else "list"
    if action in {"", "list"}:
        return _format_list(directory, user_id=user_id)
    if action == "discover":
        do_probe = probe if probe is not None else "probe" in parts[1:]
        return format_discovery(arp_text=arp_text, probe=do_probe)
    if action == "help":
        return _USAGE
    return _USAGE


def _format_list(directory: Path | None, *, user_id: str | None) -> str:
    view = public_devices(directory, user_id=user_id)
    lines = ["LAN devices:"]
    devices = view["devices"]
    if not devices:
        lines.append("none registered")
    for device in devices:
        actions = ", ".join(device["actions"]) or "no actions allowed"
        secret = "secret set" if device["secret_set"] else "no secret"
        lines.append(
            f"{device['id']}  {device['kind']}  {device['host']}:{device['port']}  {secret}  {actions}"
        )
    lines.append("Only private and link-local addresses can be registered.")
    return "\n".join(lines)


def format_discovery(*, arp_text: str | None = None, probe: bool = False) -> str:
    text = read_arp_text() if arp_text is None else arp_text
    ssdp: list[str] = []
    mdns: list[bytes] = []
    if probe:
        ssdp = probe_ssdp()
        mdns = probe_mdns()
    rows = discover_from_sources(arp_text=text, ssdp_texts=ssdp, mdns_packets=mdns)
    lines = ["LAN discovery:"]
    if not rows:
        lines.append("none")
    for row in rows:
        label = row["name"] or row["detail"] or row["source"]
        lines.append(f"{row['source']}  {row['address']}  {label}")
    return "\n".join(lines)


def describe_device(device_id: str, directory: Path | None = None, *, user_id: str | None = None) -> dict:
    device = get_device(device_id, directory, user_id=user_id)
    return {
        "id": device["id"],
        "kind": device["kind"],
        "host": device["host"],
        "actions": list(device.get("actions") or []),
        "text": mask_secrets(f"{device['kind']} {device['host']}"),
    }
