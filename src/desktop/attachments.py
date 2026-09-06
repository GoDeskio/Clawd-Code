"""User-initiated attachments for the desktop chat composer.

Nothing here polls the clipboard, captures keystrokes, or reads the screen
in the background. The UI (or Electron) must send explicit payload the user
chose to attach.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
import io
import mimetypes
from pathlib import Path
from typing import Any

from src.file_content import extract_rich_text

MAX_TEXT_BYTES = 256_000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_INLINE_UPLOAD_BYTES = 64 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
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
    media_type: str = ""
    is_image: bool = False
    data: bytes = field(default=b"", repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "text": self.text,
            "size": self.size,
            "omitted": self.omitted,
            "reason": self.reason,
            "media_type": self.media_type,
            "is_image": self.is_image,
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
    if resolved.suffix.lower() in IMAGE_SUFFIXES:
        media_type = mimetypes.guess_type(resolved.name)[0] or "image/png"
        return Attachment(
            name=resolved.name,
            kind="screenshot" if kind == "screenshot" else "image",
            path=str(resolved),
            size=size,
            media_type=media_type,
            is_image=True,
        )
    supported, extracted, note = extract_rich_text(resolved, max_chars=MAX_TEXT_BYTES)
    if supported:
        return Attachment(
            name=resolved.name,
            kind=kind,
            path=str(resolved),
            text=extracted,
            size=size,
            omitted=not bool(extracted.strip()),
            reason=note,
            media_type=mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
        )
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
        if item.is_image:
            parts.append(f"{header}\n(Image pixels are attached to this message. Use this exact path with ImageStudio when editing.)")
            continue
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
        encoded = raw.get("data_base64")
        if isinstance(encoded, str) and encoded.strip():
            name = Path(str(raw.get("name") or "upload.bin")).name or "upload.bin"
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                items.append(Attachment(name=name, kind=kind, omitted=True, reason=f"invalid uploaded data: {exc}"))
                continue
            if len(data) > MAX_INLINE_UPLOAD_BYTES:
                items.append(Attachment(name=name, kind=kind, size=len(data), omitted=True,
                                        reason=f"inline upload exceeds {MAX_INLINE_UPLOAD_BYTES} bytes"))
                continue
            media_type = str(raw.get("media_type") or mimetypes.guess_type(name)[0] or "application/octet-stream")
            items.append(Attachment(
                name=name,
                kind="image" if media_type.startswith("image/") or Path(name).suffix.lower() in IMAGE_SUFFIXES else kind,
                size=len(data),
                media_type=media_type,
                is_image=media_type.startswith("image/") or Path(name).suffix.lower() in IMAGE_SUFFIXES,
                data=data,
            ))
            continue
        if kind == "clipboard" or (not raw.get("path") and raw.get("text")):
            items.append(attach_clipboard_text(str(raw.get("text") or ""), name=str(raw.get("name") or "Clipboard")))
            continue
        path = raw.get("path")
        if isinstance(path, str) and path.strip():
            attached = attach_path(path, kind=kind if kind in {"file", "screenshot"} else "file")
            display_name = str(raw.get("name") or "").strip()
            if display_name:
                attached = replace(attached, name=Path(display_name).name)
            items.append(attached)
    return items


def image_source(item: Attachment) -> dict[str, str]:
    """Return an Anthropic-compatible base64 image source, normalizing large/unsupported files."""
    if not item.is_image or not item.path:
        raise ValueError("attachment is not an image")
    path = Path(item.path)
    raw = path.read_bytes()
    media_type = item.media_type or mimetypes.guess_type(path.name)[0] or "image/png"
    if media_type in {"image/png", "image/jpeg", "image/webp", "image/gif"} and len(raw) <= MAX_IMAGE_BYTES:
        return {"type": "base64", "media_type": media_type, "data": base64.b64encode(raw).decode("ascii")}

    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - installed by bootstrap
        raise RuntimeError("Pillow is required to attach this image") from exc
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image.convert("RGB"))
            image = background
        quality = 92
        while True:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            raw = buffer.getvalue()
            if len(raw) <= MAX_IMAGE_BYTES or max(image.size) <= 512:
                break
            image.thumbnail((max(512, int(image.width * 0.8)), max(512, int(image.height * 0.8))), Image.Resampling.LANCZOS)
            quality = max(65, quality - 7)
    return {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode("ascii")}
