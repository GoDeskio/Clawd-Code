from __future__ import annotations

import html
from html.parser import HTMLParser
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class _VisibleTextParser(HTMLParser):
    """Extract user-visible text while dropping executable/hidden document regions."""

    SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if self.depth or lowered in self.SKIP:
            self.depth += 1
            return
        values = {key.lower(): (value or "").lower() for key, value in attrs}
        style = values.get("style", "")
        if "hidden" in values or values.get("aria-hidden") == "true" or "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", ""):
            self.depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.depth and data.strip():
            self.parts.append(data)


def _is_private_host(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def _html_to_text(raw: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(raw)
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()


class WebFetchTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="WebFetch",
            description="Fetch a public URL and return visible text while dropping scripts, styles, templates, hidden elements, and private-network targets.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            is_read_only=True,
            max_result_size_chars=50_000,
        )

    def check_permissions(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> PermissionResult:
        url = tool_input.get("url", "")
        preview = url if isinstance(url, str) else ""
        return maybe_ask_for_gated_tool(
            context,
            "WebFetch",
            f"Fetch URL: {preview or '(missing)'}",
            "Allow WebFetch for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        url = tool_input["url"]
        if not isinstance(url, str) or not url:
            raise ToolInputError("url must be a non-empty string")

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ToolPermissionError("only http/https URLs are allowed")
        if not parsed.netloc:
            raise ToolInputError("url must include a network location")

        hostname = parsed.hostname or ""
        if hostname in {"localhost"} or hostname.endswith(".localhost") or _is_private_host(hostname):
            raise ToolPermissionError("refusing to fetch localhost/private network URLs")

        req = urllib.request.Request(url, headers={"User-Agent": "clawd-codex/0.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_bytes = resp.read(1_000_000)
            content_type = resp.headers.get("Content-Type", "")

        text = raw_bytes.decode("utf-8", errors="replace")
        if "text/html" in content_type:
            text = _html_to_text(text)

        if len(text) > 100_000:
            text = text[:100_000] + "\n\n... [truncated] ..."

        return ToolResult(
            name="WebFetch",
            output={"url": url, "content_type": content_type, "content": text},
        )

