"""User-initiated attachments for the desktop chat composer.

Nothing here polls the clipboard, captures keystrokes, or reads the screen
in the background. The UI (or Electron) must send explicit payload the user
chose to attach.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_TEXT_BYTES = 256_000
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ".js", ".ts",
    ".tsx", ".jsx", ".css", ".html", ".sh", ".rs", ".go", ".java", ".rb",
    ".php", ".c", ".h", ".cpp", ".hpp", ".swift", ".kt", ".sql", ".ini",
    ".cfg", ".xml", ".csv", ".log", ".env.example",
}


@dataclass(frozen=True)
class Attachment:
    name: str
    kind: str  # file | clipboard | screenshot | text
    path: str = ""
    text: str = ""
    size: int = 0
    omitted: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "text": self.text,
            "size": self.size,
            "omitted": self.omitted,
            "reason": self.reason,
        }


def _looks_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        sample = path.read_bytes()[:2048]
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def attach_path(path: str | Path, *, kind: str = "file") -> Attachment:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        return Attachment(
            name=resolved.name or str(resolved),
            kind=kind,
            path=str(resolved),
            omitted=True,
            reason="file not found",
        )
    size = resolved.stat().st_size
    if not _looks_text(resolved):
        return Attachment(
            name=resolved.name,
            kind=kind,
            path=str(resolved),
            size=size,
            omitted=True,
            reason="binary or unsupported type — path only",
        )
    if size > MAX_TEXT_BYTES:
        return Attachment(
            name=resolved.name,
            kind=kind,
            path=str(resolved),
            size=size,
            omitted=True,
            reason=f"larger than {MAX_TEXT_BYTES} bytes — path only",
        )
    text = resolved.read_text(encoding="utf-8", errors="replace")
    return Attachment(
        name=resolved.name,
        kind=kind,
        path=str(resolved),
        text=text,
        size=size,
    )


def attach_clipboard_text(text: str, *, name: str = "Clipboard") -> Attachment:
    """Attach text the user explicitly offered from the clipboard."""
    cleaned = (text or "").replace("\x00", "")
    if not cleaned.strip():
        return Attachment(name=name, kind="clipboard", omitted=True, reason="clipboard was empty")
    encoded = cleaned.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        cleaned = encoded[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")
        return Attachment(
            name=name,
            kind="clipboard",
            text=cleaned,
            size=len(encoded),
            omitted=False,
            reason="truncated to size limit",
        )
    return Attachment(name=name, kind="clipboard", text=cleaned, size=len(encoded))


def render_attachments(attachments: list[Attachment]) -> str:
    if not attachments:
        return ""
    parts: list[str] = []
    for item in attachments:
        header = f"[{item.kind} attachment: {item.name}]"
        if item.path:
            header += f" path={item.path}"
        if item.omitted and not item.text:
            parts.append(f"{header}\n({item.reason})")
            continue
        fence = "```"
        body = item.text or ""
        if "```" in body:
            fence = "````"
        parts.append(f"{header}\n{fence}\n{body}\n{fence}")
    return "\n\n".join(parts)


def attachments_from_payload(payload: list[dict[str, Any]] | None) -> list[Attachment]:
    items: list[Attachment] = []
    for raw in payload or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "file")
        if kind == "clipboard" or (not raw.get("path") and raw.get("text")):
            items.append(attach_clipboard_text(str(raw.get("text") or ""), name=str(raw.get("name") or "Clipboard")))
            continue
        path = raw.get("path")
        if isinstance(path, str) and path.strip():
            items.append(attach_path(path, kind=kind if kind in {"file", "screenshot"} else "file"))
    return items
