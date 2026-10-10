"""Per-user chat channels: Telegram, Discord, and Slack.

Inbound messages reach Jonathan only when the channel is enabled and the
sender is on that channel's allow-list. An empty allow-list drops everyone.
Bot tokens stay in the OS keyring or an encrypted file.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from src.agent.memory import current_user_id
from src.channels.parse import Inbound, parse_discord_message, parse_slack_event, parse_telegram_updates
from src.channels.transport import OFFICIAL_HOSTS, Transport, official_url, urllib_transport
from src.secret_mask import mask_secrets
from src.secret_store import get_secret, has_secret, put_secret

logger = logging.getLogger(__name__)

CHANNEL_IDS = ("telegram", "discord", "slack")
CHANNEL_LABELS = {
    "telegram": "Telegram",
    "discord": "Discord",
    "slack": "Slack",
}
_USAGE = (
    "Usage: /channels list\n"
    "Enable Telegram, Discord, or Slack in settings, store your own bot token, "
    "and list the user IDs allowed to message Jonathan. An empty list drops everyone."
)


def channels_root(directory: Path | None = None) -> Path:
    if directory is not None:
        path = directory
    else:
        raw = os.environ.get("JONATHAN_CHANNELS_DIR", "").strip()
        path = Path(raw) if raw else Path.home() / ".clawd" / "channels"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _settings_path(directory: Path | None, user_id: str | None) -> Path:
    user = user_id or current_user_id()
    return channels_root(directory) / f"settings-{user}.json"


def _split_ids(value: object) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,\s]+", value.strip()) if value.strip() else []
    elif isinstance(value, list):
        parts = [str(item).strip() for item in value]
    else:
        raise ValueError("allow list must be user IDs")
    found: list[str] = []
    for part in parts:
        if not part:
            continue
        if any(char in part for char in "\n\r\x00"):
            raise ValueError("user id is not valid")
        if part not in found:
            found.append(part)
    return found


def load_channels(directory: Path | None = None, *, user_id: str | None = None) -> dict[str, dict]:
    user = user_id or current_user_id()
    stored: dict = {}
    path = _settings_path(directory, user)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict) and isinstance(raw.get("channels"), dict):
            stored = raw["channels"]
    channels: dict[str, dict] = {}
    for name in CHANNEL_IDS:
        item = stored.get(name) if isinstance(stored.get(name), dict) else {}
        channels[name] = {
            "enabled": bool(item.get("enabled")),
            "allow_user_ids": _split_ids(item.get("allow_user_ids") or []),
        }
    return channels


def _write_channels(channels: dict[str, dict], directory: Path | None, user_id: str) -> None:
    path = _settings_path(directory, user_id)
    payload = {
        "channels": {
            name: {
                "enabled": bool(channels[name]["enabled"]),
                "allow_user_ids": list(channels[name]["allow_user_ids"]),
            }
            for name in CHANNEL_IDS
        }
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        return


def public_channels(
    directory: Path | None = None,
    *,
    user_id: str | None = None,
    backend: object | None = None,
) -> dict[str, object]:
    user = user_id or current_user_id()
    root = channels_root(directory)
    channels = load_channels(root, user_id=user)
    return {
        "channels": [
            {
                "id": name,
                "label": CHANNEL_LABELS[name],
                "enabled": channels[name]["enabled"],
                "allow_user_ids": list(channels[name]["allow_user_ids"]),
                "token_set": has_secret(root, user, f"channel-{name}", backend=backend),
            }
            for name in CHANNEL_IDS
        ]
    }


def update_channels(
    changes: object,
    directory: Path | None = None,
    *,
    user_id: str | None = None,
    backend: object | None = None,
) -> dict[str, object]:
    rows = changes
    if isinstance(changes, dict):
        rows = changes.get("channels", changes)
    if isinstance(rows, dict):
        rows = [{"id": key, **value} if isinstance(value, dict) else {"id": key} for key, value in rows.items()]
    if not isinstance(rows, list):
        raise ValueError("channels must be a list")
    user = user_id or current_user_id()
    root = channels_root(directory)
    channels = load_channels(root, user_id=user)
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("each channel must be an object")
        name = str(item.get("id") or "").strip()
        if name not in channels:
            raise ValueError(f"unknown channel: {name}")
        if "enabled" in item:
            channels[name]["enabled"] = bool(item.get("enabled"))
        if "allow_user_ids" in item or "allow" in item:
            channels[name]["allow_user_ids"] = _split_ids(item.get("allow_user_ids", item.get("allow")))
        token = item.get("token")
        if isinstance(token, str) and token.strip():
            put_secret(root, user, f"channel-{name}", token, backend=backend)
    _write_channels(channels, root, user)
    logger.info("Updated chat channel settings for %s channel(s)", len(rows))
    return public_channels(root, user_id=user, backend=backend)


def sender_allowed(channel: str, user_id: str, directory: Path | None = None, *, user_id_owner: str | None = None) -> bool:
    name = channel.strip().lower()
    channels = load_channels(directory, user_id=user_id_owner)
    row = channels.get(name)
    if row is None or not row["enabled"]:
        return False
    sender = str(user_id).strip()
    return bool(sender) and sender in row["allow_user_ids"]


def route_inbound(
    inbound: Inbound,
    reply_fn,
    *,
    directory: Path | None = None,
    user_id: str | None = None,
    backend: object | None = None,
    transport: Transport | None = None,
) -> dict[str, object]:
    """Route one allow-listed message to Jonathan and send the reply back."""
    owner = user_id or current_user_id()
    root = channels_root(directory)
    if not sender_allowed(inbound.channel, inbound.user_id, root, user_id_owner=owner):
        logger.info("Dropped %s message from a sender who is not allow-listed", inbound.channel)
        return {"accepted": False, "reply": ""}
    reply = mask_secrets(str(reply_fn(inbound.text) or ""))
    token = get_secret(root, owner, f"channel-{inbound.channel}", backend=backend)
    sent = False
    if token and inbound.reply_to:
        poster = transport or urllib_transport
        _send(inbound.channel, token, inbound.reply_to, reply, poster)
        sent = True
        logger.info("Sent %s reply", inbound.channel)
    return {"accepted": True, "reply": reply, "sent": sent}


def poll_telegram(
    token: str,
    *,
    offset: int = 0,
    transport: Transport | None = None,
) -> list[Inbound]:
    poster = transport or urllib_transport
    url = official_url("telegram", f"https://api.telegram.org/bot{token}/getUpdates")
    payload = poster("POST", url, {}, {"offset": offset, "timeout": 0})
    return parse_telegram_updates(payload)


def _send(channel: str, token: str, reply_to: str, text: str, transport: Transport) -> None:
    if channel == "telegram":
        url = official_url("telegram", f"https://api.telegram.org/bot{token}/sendMessage")
        transport("POST", url, {}, {"chat_id": reply_to, "text": text})
        return
    if channel == "discord":
        url = official_url("discord", f"https://discord.com/api/v10/channels/{reply_to}/messages")
        transport("POST", url, {"Authorization": f"Bot {token}"}, {"content": text})
        return
    if channel == "slack":
        url = official_url("slack", "https://slack.com/api/chat.postMessage")
        transport("POST", url, {"Authorization": f"Bearer {token}"}, {"channel": reply_to, "text": text})
        return
    raise ValueError(f"unknown channel: {channel}")


def format_channels_command(args: str, *, directory: Path | None = None, user_id: str | None = None) -> str:
    parts = args.split()
    if parts and parts[0] not in {"list", "help"}:
        return _USAGE
    view = public_channels(directory, user_id=user_id)
    lines = ["Chat channels:"]
    for row in view["channels"]:
        state = "enabled" if row["enabled"] else "disabled"
        token = "token set" if row["token_set"] else "no token"
        allow = ", ".join(row["allow_user_ids"]) or "allow-list empty"
        lines.append(f"{row['id']}  {row['label']}  {state}  {token}  {allow}")
    lines.append("Empty allow-lists drop every inbound message.")
    return "\n".join(lines)


def ingest_payload(
    channel: str,
    payload: object,
    reply_fn,
    *,
    directory: Path | None = None,
    user_id: str | None = None,
    backend: object | None = None,
    transport: Transport | None = None,
) -> list[dict[str, object]]:
    """Parse a platform payload and route each message. Used by tests and polls."""
    name = channel.strip().lower()
    messages: list[Inbound] = []
    if name == "telegram":
        messages = parse_telegram_updates(payload)
    elif name == "discord":
        one = parse_discord_message(payload)
        messages = [one] if one else []
    elif name == "slack":
        one = parse_slack_event(payload)
        messages = [one] if one else []
    else:
        raise ValueError(f"unknown channel: {name}")
    return [
        route_inbound(
            message,
            reply_fn,
            directory=directory,
            user_id=user_id,
            backend=backend,
            transport=transport,
        )
        for message in messages
    ]
