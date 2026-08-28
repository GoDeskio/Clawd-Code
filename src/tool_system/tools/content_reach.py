"""Public content-channel discovery for RSS and YouTube."""
from __future__ import annotations

import importlib.util
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec
from .web_fetch import _is_private_host


def _public_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolInputError("url must be an absolute http/https URL")
    host = parsed.hostname or ""
    if host == "localhost" or host.endswith(".localhost") or _is_private_host(host):
        raise ToolInputError("private or local network URLs are not allowed")
    return value


def _channel_status() -> dict[str, Any]:
    return {
        "web": {"ready": True, "tool": "WebFetch"},
        "rss": {"ready": importlib.util.find_spec("feedparser") is not None, "engine": "feedparser"},
        "youtube": {"ready": importlib.util.find_spec("yt_dlp") is not None, "engine": "yt-dlp public metadata/captions"},
        "github_gitlab": {"ready": True, "tool": "Repository and connector cards"},
        "authenticated_social": {"ready": True, "tool": "explicit OAuth/password connector cards", "cookies_read_automatically": False},
    }


def _rss(url: str, limit: int) -> dict[str, Any]:
    try:
        import feedparser
    except ImportError as exc:
        raise ToolInputError("RSS support is not installed. Run Jonathan's dependency repair and retry.") from exc
    parsed = feedparser.parse(url, request_headers={"User-Agent": "JonathanAi/0.4.8"})
    if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", []):
        raise ToolInputError(f"RSS/Atom feed could not be parsed: {getattr(parsed, 'bozo_exception', 'unknown error')}")
    entries = []
    for item in list(getattr(parsed, "entries", []))[:limit]:
        entries.append({
            "title": str(item.get("title") or ""),
            "url": str(item.get("link") or ""),
            "published": str(item.get("published") or item.get("updated") or ""),
            "summary": re.sub(r"<[^>]+>", " ", str(item.get("summary") or ""))[:4000],
        })
    feed = getattr(parsed, "feed", {})
    return {"url": url, "title": str(feed.get("title") or ""), "description": str(feed.get("subtitle") or feed.get("description") or ""), "entries": entries}


def _caption_text(raw: bytes, content_type: str) -> str:
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type or text.lstrip().startswith("{"):
        try:
            payload = json.loads(text)
            lines = []
            for event in payload.get("events", []):
                segment = "".join(str(item.get("utf8") or "") for item in event.get("segs", []))
                segment = re.sub(r"\s+", " ", segment).strip()
                if segment and segment != "[Music]":
                    lines.append(segment)
            return " ".join(lines)
        except (ValueError, TypeError):
            pass
    lines = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith(("WEBVTT", "Kind:", "Language:")) or "-->" in cleaned or cleaned.isdigit():
            continue
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        if not lines or lines[-1] != cleaned:
            lines.append(cleaned)
    return " ".join(lines)


def _youtube(url: str, language: str) -> dict[str, Any]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise ToolInputError("YouTube metadata support is not installed. Run Jonathan's dependency repair and retry.") from exc
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 30}
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
    tracks = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    languages = list(tracks) or list(automatic)
    chosen = language if language in tracks or language in automatic else next((item for item in languages if item.startswith(language.split("-")[0])), languages[0] if languages else "")
    candidates = (tracks.get(chosen) or automatic.get(chosen) or []) if chosen else []
    preferred = next((item for item in candidates if item.get("ext") == "json3"), None) or next((item for item in candidates if item.get("ext") in {"vtt", "srv3", "ttml"}), None)
    transcript = ""
    if preferred and preferred.get("url"):
        request = urllib.request.Request(str(preferred["url"]), headers={"User-Agent": "Mozilla/5.0 JonathanAi/0.4.8"})
        with urllib.request.urlopen(request, timeout=30) as response:
            transcript = _caption_text(response.read(5_000_000), response.headers.get("Content-Type", ""))
    return {
        "url": str(info.get("webpage_url") or url),
        "id": str(info.get("id") or ""),
        "title": str(info.get("title") or ""),
        "channel": str(info.get("channel") or info.get("uploader") or ""),
        "duration_seconds": info.get("duration"),
        "description": str(info.get("description") or "")[:12_000],
        "caption_language": chosen,
        "available_caption_languages": languages[:50],
        "transcript": transcript[:100_000],
        "transcript_available": bool(transcript),
    }


class ContentReachTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ContentReach",
            description="Check public content-channel readiness, read RSS/Atom feeds, and retrieve public YouTube metadata/captions without copying browser cookies. Authenticated social services remain explicit connector cards.",
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["status", "rss", "youtube"]},
                "url": {"type": "string"}, "language": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }, "required": ["action"]},
            is_destructive=True,
            max_result_size_chars=120_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") == "status":
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "ContentReach", f"Read public {tool_input.get('action')} content from {tool_input.get('url') or '(missing URL)'}", "Allow public content reads for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "status":
            return ToolResult(name="ContentReach", output={"channels": _channel_status()})
        url = _public_url(str(tool_input.get("url") or ""))
        if action == "rss":
            output = _rss(url, int(tool_input.get("limit") or 20))
        else:
            output = _youtube(url, str(tool_input.get("language") or "en"))
        return ToolResult(name="ContentReach", output={"ok": True, "action": action, **output})
