"""Conversation management for Clawd Codex."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Union

# Anthropic Messages API: tool_result.content must be a string or a list of
# content blocks. A bare dict/object is a 400
# (messages.N.content.0.tool_result.content: Found an object...).
_ANTHROPIC_CONTENT_BLOCK_TYPES = frozenset({
    "text",
    "image",
    "document",
    "thinking",
    "redacted_thinking",
    "tool_use",
    "server_tool_use",
    "web_search_tool_result",
    "search_result",
    "container_upload",
    "code_execution_tool_result",
    "bash_code_execution_tool_result",
    "text_editor_code_execution_tool_result",
    "mcp_tool_use",
    "mcp_tool_result",
})


def _is_anthropic_content_block(item: Any) -> bool:
    """True when item looks like an Anthropic content block, not a tool dict."""
    if not isinstance(item, dict):
        return False
    block_type = item.get("type")
    if block_type not in _ANTHROPIC_CONTENT_BLOCK_TYPES:
        return False
    # Read/Write/etc. return {"type": "text", "filePath": ...} — that is a tool
    # payload, not a text block. Only keep real text blocks.
    if block_type == "text":
        return isinstance(item.get("text"), str)
    if block_type in {"image", "document"}:
        return "source" in item
    if block_type == "thinking":
        return "thinking" in item
    return True


def normalize_tool_result_content(content: Any) -> Union[str, list[dict[str, Any]]]:
    """Coerce tool_result.content to a string or list of Anthropic content blocks.

    Dicts, objects, and non-block lists are json.dumps'd so resumed sessions that
    already stored object-shaped tool results stay valid on the next Anthropic turn.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if all(_is_anthropic_content_block(item) for item in content):
            return content
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, (dict, bool, int, float)):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def sanitize_anthropic_messages(messages: list[Any]) -> list[Any]:
    """Copy messages and stringify any object-shaped tool_result.content."""
    prepared: list[Any] = []
    for msg in messages:
        if not isinstance(msg, dict):
            prepared.append(msg)
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            prepared.append(msg)
            continue
        new_content: list[Any] = []
        changed = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                raw = block.get("content")
                normalized = normalize_tool_result_content(raw)
                if normalized is not raw:
                    block = {**block, "content": normalized}
                    changed = True
            new_content.append(block)
        if changed:
            prepared.append({**msg, "content": new_content})
        else:
            prepared.append(msg)
    return prepared


@dataclass
class TextContentBlock:
    """A text content block."""
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseContentBlock:
    """A tool use content block."""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultContentBlock:
    """A tool result content block."""
    type: str = "tool_result"
    tool_use_id: str = ""
    content: Union[str, list[dict[str, Any]], dict[str, Any]] = ""
    is_error: bool = False


ContentBlock = Union[TextContentBlock, ToolUseContentBlock, ToolResultContentBlock]


@dataclass
class Message:
    """Conversation message."""
    role: str  # "user", "assistant", "system"
    content: Union[str, list[ContentBlock]]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    # Internal marker for messages that should be filtered from API (e.g., compact boundary)
    _is_internal: bool = field(default=False, repr=False)


@dataclass
class Conversation:
    """Conversation manager."""
    messages: list[Message] = field(default_factory=list)
    max_history: int = 100

    def add_message(self, role: str, content: Union[str, list[ContentBlock]]):
        """Add a message to conversation."""
        if len(self.messages) >= self.max_history:
            self.messages.pop(0)

        self.messages.append(Message(role=role, content=content))

    def add_user_message(self, text: str):
        """Add a plain user text message."""
        self.add_message("user", text)

    def add_assistant_message(self, content: Union[str, list[ContentBlock]]):
        """Add an assistant message (text or tool use)."""
        self.add_message("assistant", content)

    def add_tool_result_message(self, tool_use_id: str, content: Any, is_error: bool = False):
        """Add a tool result message (dict/list tool output is stringified)."""
        block = ToolResultContentBlock(
            type="tool_result",
            tool_use_id=tool_use_id,
            content=normalize_tool_result_content(content),
            is_error=is_error
        )
        self.add_message("user", [block])

    def get_messages(self) -> list[dict]:
        """Get messages in API format (Anthropic style)."""
        api_messages = []
        for msg in self.messages:
            # Skip internal messages (e.g., compact boundary markers)
            if getattr(msg, "_is_internal", False):
                continue
            if isinstance(msg.content, str):
                api_messages.append({"role": msg.role, "content": msg.content})
            else:
                content_blocks = []
                for block in msg.content:
                    if isinstance(block, TextContentBlock):
                        content_blocks.append({"type": "text", "text": block.text})
                    elif isinstance(block, ToolUseContentBlock):
                        content_blocks.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input
                        })
                    elif isinstance(block, ToolResultContentBlock):
                        content_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": block.tool_use_id,
                            "content": normalize_tool_result_content(block.content),
                            "is_error": block.is_error
                        })
                api_messages.append({"role": msg.role, "content": content_blocks})
        return api_messages

    def clear(self):
        """Clear conversation."""
        self.messages.clear()

    def to_dict(self) -> dict:
        """Serialize conversation."""
        messages_data = []
        for msg in self.messages:
            if isinstance(msg.content, str):
                content_data = msg.content
            else:
                content_data = []
                for block in msg.content:
                    if isinstance(block, TextContentBlock):
                        content_data.append({"type": "text", "text": block.text})
                    elif isinstance(block, ToolUseContentBlock):
                        content_data.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input
                        })
                    elif isinstance(block, ToolResultContentBlock):
                        content_data.append({
                            "type": "tool_result",
                            "tool_use_id": block.tool_use_id,
                            "content": normalize_tool_result_content(block.content),
                            "is_error": block.is_error
                        })
            messages_data.append({
                "role": msg.role,
                "content": content_data,
                "timestamp": msg.timestamp,
                "_is_internal": getattr(msg, "_is_internal", False),
            })
        return {
            "messages": messages_data,
            "max_history": self.max_history
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Conversation':
        """Deserialize conversation."""
        conv = cls(max_history=data.get("max_history", 100))
        for msg_data in data.get("messages", []):
            content = msg_data["content"]
            if isinstance(content, str):
                msg_content = content
            else:
                msg_content = []
                for block_data in content:
                    block_type = block_data.get("type")
                    if block_type == "text":
                        msg_content.append(TextContentBlock(type="text", text=block_data.get("text", "")))
                    elif block_type == "tool_use":
                        msg_content.append(ToolUseContentBlock(
                            type="tool_use",
                            id=block_data.get("id", ""),
                            name=block_data.get("name", ""),
                            input=block_data.get("input", {})
                        ))
                    elif block_type == "tool_result":
                        msg_content.append(ToolResultContentBlock(
                            type="tool_result",
                            tool_use_id=block_data.get("tool_use_id", ""),
                            content=normalize_tool_result_content(block_data.get("content", "")),
                            is_error=block_data.get("is_error", False)
                        ))
            conv.messages.append(Message(
                role=msg_data["role"],
                content=msg_content,
                timestamp=msg_data.get("timestamp", ""),
                _is_internal=msg_data.get("_is_internal", False),
            ))
        return conv
