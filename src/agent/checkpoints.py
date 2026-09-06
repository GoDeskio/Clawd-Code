"""Recoverable per-conversation checkpoints for retry, undo, and crash recovery."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent.conversation import Conversation, ImageContentBlock, TextContentBlock
from src.agent.session import Session

_LOCK = threading.RLock()


def checkpoint_dir() -> Path:
    path = Path.home() / ".clawd" / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(session_id: str) -> Path:
    return checkpoint_dir() / f"{session_id}.json"


def _write(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def create_checkpoint(session: Session, *, reason: str = "before-run", keep: int = 20) -> dict[str, Any]:
    with _LOCK:
        path = _path(session.session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"checkpoints": []}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            data = {"checkpoints": []}
        item = {
            "id": uuid.uuid4().hex[:12],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "title": session.display_title(),
            "provider": session.provider,
            "model": session.model,
            "workspace": session.workspace,
            "conversation": session.conversation.to_dict(),
            "token_usage": session.token_usage,
        }
        rows = [row for row in data.get("checkpoints", []) if isinstance(row, dict)]
        rows.append(item)
        _write(path, {"session_id": session.session_id, "checkpoints": rows[-max(1, keep):]})
        return {key: value for key, value in item.items() if key != "conversation"}


def list_checkpoints(session_id: str) -> list[dict[str, Any]]:
    path = _path(session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    rows = [row for row in data.get("checkpoints", []) if isinstance(row, dict)]
    return [{key: value for key, value in row.items() if key != "conversation"} for row in reversed(rows)]


def restore_checkpoint(session: Session, checkpoint_id: str = "") -> dict[str, Any]:
    path = _path(session.session_id)
    if not path.exists():
        raise ValueError("No recovery checkpoint exists for this conversation.")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in data.get("checkpoints", []) if isinstance(row, dict)]
    chosen = next((row for row in reversed(rows) if not checkpoint_id or row.get("id") == checkpoint_id), None)
    if chosen is None:
        raise ValueError("Checkpoint not found.")
    session.conversation = Conversation.from_dict(chosen.get("conversation") or {})
    session.token_usage = dict(chosen.get("token_usage") or {})
    session.save()
    return {"restored": chosen.get("id"), "session": session.to_summary(), "messages": session.export_messages()}


def undo_last_turn(session: Session) -> dict[str, Any]:
    messages = session.conversation.messages
    user_index = next((
        index for index in range(len(messages) - 1, -1, -1)
        if messages[index].role == "user"
        and not getattr(messages[index], "_is_internal", False)
        and (
            isinstance(messages[index].content, str)
            or any(isinstance(block, (TextContentBlock, ImageContentBlock)) for block in (messages[index].content or []))
        )
    ), None)
    if user_index is None:
        raise ValueError("There is no completed turn to undo.")
    create_checkpoint(session, reason="before-undo")
    del messages[user_index:]
    session.save()
    return {"undone": True, "session": session.to_summary(), "messages": session.export_messages()}


def prepare_retry(session: Session) -> str:
    messages = session.conversation.messages
    user_index = next((index for index in range(len(messages) - 1, -1, -1) if messages[index].role == "user" and isinstance(messages[index].content, str)), None)
    if user_index is None:
        raise ValueError("There is no user prompt to retry.")
    prompt = str(messages[user_index].content).strip()
    if not prompt:
        raise ValueError("The last prompt is empty.")
    create_checkpoint(session, reason="before-retry")
    del messages[user_index:]
    session.save()
    return prompt
