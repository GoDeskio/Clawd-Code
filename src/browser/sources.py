"""Allowlisted browser downloads.

Chrome builds come from Chrome for Testing. Playwright builds come from the
official Playwright CDN. npmmirror and every other host are refused before a
request is made.
"""

from __future__ import annotations

from urllib.parse import urlsplit


class BrowserError(ValueError):
    """A browser download or action cannot be completed."""


BROWSER_EXTRA_HINT = 'Browser extra is not installed. Run: pip install "clawd-codex[browser]"'

_BLOCKED_MARKERS = (
    "npmmirror.com",
    "npmmirror",
    "registry.npmmirror",
)

_PLAYWRIGHT_HOSTS = frozenset(
    {
        "cdn.playwright.dev",
        "playwright.azureedge.net",
        "playwright.download.prss.microsoft.com",
    }
)


def assert_browser_download_url(url: str) -> str:
    """Refuse every browser download that is not an official source."""
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    lowered = url.lower()
    if parsed.scheme != "https" or not host:
        raise BrowserError(f"Refusing browser download URL {url!r}.")
    if any(marker in host or marker in lowered for marker in _BLOCKED_MARKERS):
        raise BrowserError(
            "Refusing npmmirror. Download Chrome for Testing or the official Playwright build."
        )
    path = parsed.path or ""
    if host == "googlechromelabs.github.io" and path.startswith("/chrome-for-testing"):
        return url
    if host == "storage.googleapis.com" and path.startswith("/chrome-for-testing-public/"):
        return url
    if host == "edgedl.me.gvt1.com" and "/chrome/chrome-for-testing/" in path:
        return url
    if host in _PLAYWRIGHT_HOSTS and "/chromium" in path:
        return url
    raise BrowserError(
        f"Refusing browser host {host}. Use Chrome for Testing or the official Playwright CDN."
    )


def download_browser(url: str, dest, *, fetch) -> None:
    """Download one allowlisted browser archive. ``fetch`` is not called for a refused host."""
    from pathlib import Path

    assert_browser_download_url(url)
    data = fetch(url)
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
