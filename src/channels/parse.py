"""Turn Telegram, Discord, and Slack payloads into plain inbound messages.

Only these three channels are supported. Payloads are data, not instructions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Inbound:
    channel: str
    user_id: str
    text: str
    reply_to: str


def parse_telegram_updates(payload: object) -> list[Inbound]:
    if not isinstance(payload, dict):
        return []
    found: list[Inbound] = []
    for update in payload.get("result") or []:
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            continue
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        user_id = str(sender.get("id") or "").strip()
        reply_to = str(chat.get("id") or user_id).strip()
        text = str(message.get("text") or message.get("caption") or "").strip()
        if user_id and text:
            found.append(Inbound("telegram", user_id, text, reply_to))
    return found


def parse_discord_message(payload: object) -> Inbound | None:
    if not isinstance(payload, dict):
        return None
    event = payload.get("d") if payload.get("t") == "MESSAGE_CREATE" and isinstance(payload.get("d"), dict) else payload
    if not isinstance(event, dict):
        return None
    author = event.get("author") if isinstance(event.get("author"), dict) else {}
    user_id = str(author.get("id") or "").strip()
    text = str(event.get("content") or "").strip()
    reply_to = str(event.get("channel_id") or "").strip()
    if not user_id or not text or not reply_to:
        return None
    if author.get("bot") is True:
        return None
    return Inbound("discord", user_id, text, reply_to)


def parse_slack_event(payload: object) -> Inbound | None:
    if not isinstance(payload, dict):
        return None
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    if not isinstance(event, dict):
        return None
    if event.get("bot_id") or event.get("subtype"):
        return None
    user_id = str(event.get("user") or "").strip()
    text = str(event.get("text") or "").strip()
    reply_to = str(event.get("channel") or "").strip()
    if not user_id or not text or not reply_to:
        return None
    return Inbound("slack", user_id, text, reply_to)
