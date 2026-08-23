"""Session management with persistence."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from .conversation import Conversation


def empty_token_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def merge_token_usage(current: dict | None, delta: dict | None) -> dict:
    """Add one turn's tokens onto the running chat total. Informational only."""
    totals = dict(current) if isinstance(current, dict) else empty_token_usage()
    extra = delta if isinstance(delta, dict) else {}
    inp = int(extra.get("input_tokens") or extra.get("prompt_tokens") or 0)
    out = int(extra.get("output_tokens") or extra.get("completion_tokens") or 0)
    totals["input_tokens"] = int(totals.get("input_tokens") or 0) + max(inp, 0)
    totals["output_tokens"] = int(totals.get("output_tokens") or 0) + max(out, 0)
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    return totals


def session_dir() -> Path:
    """Return the local session directory (~/.clawd/sessions)."""
    path = Path.home() / ".clawd" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
        }

        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)

    @classmethod
    def load(cls, session_id: str) -> Optional['Session']:
        """Load session from disk."""
        session_file = session_dir() / f"{session_id}.json"

        if not session_file.exists():
            return None

        with open(session_file, 'r') as f:
            data = json.load(f)

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
        )

    @classmethod
    def list_sessions(cls) -> list[dict]:
        """List locally saved sessions, newest first."""
        items: list[dict] = []
        for path in session_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
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
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(
            session_id=session_id,
            provider=provider,
            model=model,
            workspace=workspace,
        )
