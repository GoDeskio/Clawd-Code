"""Session management with persistence."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from .conversation import Conversation, sanitize_legacy_binary_upload_text


def empty_token_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated": False}


def merge_token_usage(current: dict | None, delta: dict | None) -> dict:
    """Add one turn's tokens onto the running chat total. Informational only."""
    totals = dict(current) if isinstance(current, dict) else empty_token_usage()
    extra = delta if isinstance(delta, dict) else {}
    inp = int(extra.get("input_tokens") or extra.get("prompt_tokens") or 0)
    out = int(extra.get("output_tokens") or extra.get("completion_tokens") or 0)
    totals["input_tokens"] = int(totals.get("input_tokens") or 0) + max(inp, 0)
    totals["output_tokens"] = int(totals.get("output_tokens") or 0) + max(out, 0)
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    totals["estimated"] = bool(totals.get("estimated") or extra.get("estimated"))
    return totals


def session_dir() -> Path:
    """Return the local session directory (~/.clawd/sessions)."""
    path = Path.home() / ".clawd" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json_file(path: Path) -> dict:
    """Read session JSON as UTF-8 and require an object payload."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("session JSON must be an object", "", 0)
    return data


def _message_text(content) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)


def _title_from_conversation(conversation: Conversation) -> str:
    for msg in conversation.messages:
        if msg.role != "user":
            continue
        if isinstance(msg.content, str) and msg.content.strip():
            text = msg.content.strip().splitlines()[0]
            return text if len(text) <= 72 else text[:69] + "..."
    return "New chat"


@dataclass
class Session:
    """Session manager with persistence."""
    session_id: str
    provider: str
    model: str
    conversation: Conversation = field(default_factory=Conversation)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    workspace: str = ""
    title: str = "New chat"
    custom_title: bool = False
    token_usage: dict = field(default_factory=empty_token_usage)
    media_items: list[dict] = field(default_factory=list)

    def preview_title(self) -> str:
        derived = _title_from_conversation(self.conversation)
        if derived != "New chat":
            return derived
        return self.title or "New chat"

    def display_title(self) -> str:
        if self.custom_title and str(self.title or "").strip():
            return str(self.title).strip()
        return self.preview_title()

    def rename(self, title: str) -> str:
        cleaned = " ".join(str(title or "").split())
        if not cleaned:
            raise ValueError("title cannot be empty")
        if len(cleaned) > 120:
            cleaned = cleaned[:117] + "..."
        self.title = cleaned
        self.custom_title = True
        self.save()
        return self.title

    def to_summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.display_title(),
            "custom_title": self.custom_title,
            "provider": self.provider,
            "model": self.model,
            "workspace": self.workspace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.conversation.messages),
            "token_usage": merge_token_usage(self.token_usage, None),
        }

    def record_usage(self, usage: dict | None) -> dict:
        self.token_usage = merge_token_usage(self.token_usage, usage)
        return dict(self.token_usage)

    def record_artifact(self, artifact: dict | None, *, caption: str = "Generated file") -> dict | None:
        """Attach a safe, persistent artifact descriptor to this conversation."""
        if not isinstance(artifact, dict) or not artifact.get("name"):
            return None
        allowed = {
            "id", "name", "size", "updated_at", "download_url", "view_url",
            "media_type", "is_image",
        }
        item = {key: artifact[key] for key in allowed if key in artifact}
        item["caption"] = str(caption or "Generated file")
        item["timestamp"] = datetime.now().isoformat()
        identity = str(item.get("id") or item.get("name"))
        for existing in self.media_items:
            if str(existing.get("id") or existing.get("name")) == identity:
                return existing
        self.media_items.append(item)
        return item

    def export_messages(self) -> list[dict]:
        """User-visible rich transcript, including images and downloadable artifacts."""
        rows: list[dict] = []
        for msg in self.conversation.messages:
            if getattr(msg, "_is_internal", False):
                continue
            if msg.role not in {"user", "assistant", "system"}:
                continue
            if isinstance(msg.content, str):
                visible = sanitize_legacy_binary_upload_text(msg.content)
                if visible.strip():
                    rows.append({"role": msg.role, "content": visible, "timestamp": msg.timestamp})
                continue
            blocks: list[dict] = []
            visible_text = _message_text(msg.content)
            attachment_names = re.findall(r"\[(?:image|screenshot) attachment: ([^\]]+)\]", visible_text)
            image_index = 0
            for block in msg.content or []:
                block_type = getattr(block, "type", "")
                if block_type == "text" and str(getattr(block, "text", "")).strip():
                    display_text = getattr(block, "display_text", None)
                    if display_text is None or str(display_text).strip():
                        blocks.append({"type": "text", "text": str(block.text if display_text is None else display_text)})
                elif block_type == "image" and isinstance(getattr(block, "source", None), dict):
                    source = dict(block.source)
                    media_type = str(source.get("media_type") or "image/png")
                    extension = {"image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(media_type, "png")
                    name = attachment_names[image_index] if image_index < len(attachment_names) else f"uploaded-image-{image_index + 1}.{extension}"
                    blocks.append({"type": "image", "source": source, "name": name})
                    image_index += 1
                elif block_type == "attachment" and str(getattr(block, "download_url", "")):
                    blocks.append({
                        "type": "attachment",
                        "name": str(getattr(block, "name", "attachment")),
                        "download_url": str(block.download_url),
                        "media_type": str(getattr(block, "media_type", "application/octet-stream")),
                        "size": int(getattr(block, "size", 0) or 0),
                    })
            if blocks:
                rows.append({"role": msg.role, "content": blocks, "timestamp": msg.timestamp})
        for item in self.media_items:
            rows.append({
                "role": "assistant",
                "content": [{"type": "artifact", **dict(item)}],
                "timestamp": str(item.get("timestamp") or item.get("updated_at") or ""),
            })
        return sorted(rows, key=lambda row: str(row.get("timestamp") or ""))

    def save(self):
        """Save session to disk."""
        target_dir = session_dir()
        session_file = target_dir / f"{self.session_id}.json"
        if not self.custom_title:
            self.title = self.preview_title()
        self.updated_at = datetime.now().isoformat()

        session_data = {
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "conversation": self.conversation.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workspace": self.workspace,
            "title": self.title,
            "custom_title": self.custom_title,
            "token_usage": merge_token_usage(self.token_usage, None),
            "media_items": self.media_items,
        }

        temp_file = session_file.with_name(
            f"{session_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temp_file.write_text(
                json.dumps(session_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temp_file, session_file)
        finally:
            try:
                temp_file.unlink()
            except FileNotFoundError:
                pass

    @classmethod
    def load(cls, session_id: str) -> Optional['Session']:
        """Load session from disk."""
        session_file = session_dir() / f"{session_id}.json"

        if not session_file.exists():
            return None

        try:
            data = _read_json_file(session_file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

        conversation = Conversation.from_dict(data.get("conversation") or {})
        return cls(
            session_id=data["session_id"],
            provider=data["provider"],
            model=data["model"],
            conversation=conversation,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            workspace=data.get("workspace", ""),
            title=data.get("title") or _title_from_conversation(conversation),
            custom_title=bool(data.get("custom_title")),
            token_usage=merge_token_usage(data.get("token_usage"), None),
            media_items=[dict(item) for item in data.get("media_items") or [] if isinstance(item, dict)],
        )

    @classmethod
    def list_sessions(cls) -> list[dict]:
        """List locally saved sessions, newest first."""
        items: list[dict] = []
        for path in session_dir().glob("*.json"):
            try:
                data = _read_json_file(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            conversation = Conversation.from_dict(data.get("conversation") or {})
            custom_title = bool(data.get("custom_title"))
            stored = str(data.get("title") or "").strip()
            if custom_title and stored:
                title = stored
            else:
                title = stored or _title_from_conversation(conversation)
            items.append({
                "session_id": data.get("session_id", path.stem),
                "title": title,
                "custom_title": custom_title,
                "provider": data.get("provider", ""),
                "model": data.get("model", ""),
                "workspace": data.get("workspace", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "message_count": len(conversation.messages),
                "token_usage": merge_token_usage(data.get("token_usage"), None),
            })
        items.sort(key=lambda row: row.get("updated_at") or row.get("created_at") or "", reverse=True)
        return items

    @classmethod
    def create(cls, provider: str, model: str, workspace: str = "") -> 'Session':
        """Create a new session."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        return cls(
            session_id=session_id,
            provider=provider,
            model=model,
            workspace=workspace,
        )
