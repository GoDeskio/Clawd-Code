"""Browser actions on a persistent Chrome profile.

Form submits, purchases, and logins are marked sensitive so the tool asks
even after a session-wide Browser grant. Screenshot text is redacted in the
page before capture, and logs go through the secret mask.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..secret_mask import mask_secrets
from ..tool_system.permission_handler import PermissionResult
from ..tool_system.permissions import maybe_ask_for_gated_tool
from .cdp import BrowserTransport, attach_profile
from .profile import profile_dir
from .sources import BrowserError

logger = logging.getLogger(__name__)

ACTIONS = frozenset(
    {
        "navigate",
        "click",
        "type",
        "fill",
        "press",
        "screenshot",
        "scroll",
        "select",
        "wait",
        "submit",
        "purchase",
        "login",
        "go_back",
        "reload",
        "list_tabs",
        "new_tab",
        "close_tab",
        "close_session",
    }
)

_LOGIN_RE = re.compile(r"\b(log\s*in|sign\s*in|password|passwd)\b", re.IGNORECASE)
_PURCHASE_RE = re.compile(
    r"\b(buy|purchase|checkout|pay now|place order|add to cart)\b",
    re.IGNORECASE,
)
_SUBMIT_RE = re.compile(r"\b(submit|sign up|register)\b", re.IGNORECASE)

# Clears password fields and replaces visible secret-shaped text before a shot.
REDACT_EXPRESSION = r"""
(() => {
  const mask = (value) => {
    const text = String(value || "");
    if (text.length <= 8) return "*".repeat(text.length);
    return text.slice(0, 4) + "*".repeat(text.length - 8) + text.slice(-4);
  };
  for (const node of document.querySelectorAll("input[type=password], input[name*=password i]")) {
    node.value = "";
  }
  const pattern = /sk-[A-Za-z0-9_-]{20,}|password\s*[:=]\s*\S+/gi;
  const walker = document.createTreeWalker(document.body || document, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    if (pattern.test(node.nodeValue || "")) {
      node.nodeValue = (node.nodeValue || "").replace(pattern, (hit) => mask(hit));
    }
    pattern.lastIndex = 0;
  }
  return "redacted";
})()
""".strip()


def _blob(tool_input: dict[str, Any]) -> str:
    parts = [
        str(tool_input.get("action") or ""),
        str(tool_input.get("url") or ""),
        str(tool_input.get("selector") or ""),
        str(tool_input.get("text") or ""),
        str(tool_input.get("key") or ""),
    ]
    return " ".join(parts)


def sensitive_kind(tool_input: dict[str, Any]) -> str | None:
    """Return submit, purchase, or login when this action needs its own approval."""
    action = str(tool_input.get("action") or "").strip().lower()
    if action in {"submit", "purchase", "login"}:
        return action
    blob = _blob(tool_input)
    selector = str(tool_input.get("selector") or "").lower()
    if action in {"type", "fill", "click", "press"} and (
        "type=password" in selector or "[name=password]" in selector or "password" in selector
    ):
        return "login"
    if action in {"type", "fill", "click", "press"} and _LOGIN_RE.search(blob):
        return "login"
    if action in {"click", "press"} and (_SUBMIT_RE.search(blob) or "type=submit" in selector):
        return "submit"
    if action in {"click", "press"} and _PURCHASE_RE.search(blob):
        return "purchase"
    return None


def check_browser_permission(tool_input: dict[str, Any], context: object) -> PermissionResult:
    """Ask through the desktop gate. Sensitive actions ignore session grants."""
    action = str(tool_input.get("action") or "").strip().lower() or "browser"
    kind = sensitive_kind(tool_input)
    if kind is not None:
        label = {"submit": "form submit", "purchase": "purchase", "login": "login"}[kind]
        return PermissionResult.ask(
            message=f"Approve this browser {label} ({action}) before it runs.",
            suggestion=f"Approve this {label}",
        )
    return maybe_ask_for_gated_tool(
        context,
        "Browser",
        f"Browser {action}",
        "Allow Browser for the rest of this session",
    )


def run_browser_action(
    tool_input: dict[str, Any],
    *,
    transport: BrowserTransport,
    profile_root: Path | None = None,
) -> dict[str, Any]:
    action = str(tool_input.get("action") or "").strip().lower()
    if action not in ACTIONS:
        known = ", ".join(sorted(ACTIONS))
        raise BrowserError(f"Unknown browser action {action!r}. Known actions: {known}.")
    name = str(tool_input.get("profile") or "default")
    data_dir = profile_dir(name, profile_root)
    url = str(tool_input.get("url") or "")
    logger.info("browser action=%s profile=%s url=%s", action, name, mask_secrets(url))
    if action == "close_session":
        transport.close()
        return {
            "action": action,
            "profile": name,
            "profile_dir": str(data_dir),
            "persisted": data_dir.is_dir(),
        }
    attach_profile(name, transport, profile_root)
    if action == "navigate":
        if not url:
            raise BrowserError("navigate needs a url.")
        transport.send("Page.navigate", {"url": url})
        title = _eval_text(transport, "document.title")
        body = _eval_text(transport, "document.body ? document.body.innerText : ''")
        return {
            "action": action,
            "url": mask_secrets(url),
            "title": mask_secrets(title),
            "text": mask_secrets(body)[:8000],
            "profile": name,
            "profile_dir": str(data_dir),
        }
    if action == "screenshot":
        transport.send("Runtime.evaluate", {"expression": REDACT_EXPRESSION})
        shot = transport.send("Page.captureScreenshot", {"format": "png"})
        raw = shot.get("data")
        image = raw if isinstance(raw, (bytes, bytearray)) else b""
        target = data_dir / "last-screenshot.png"
        if image:
            target.write_bytes(bytes(image))
        return {
            "action": action,
            "redacted": True,
            "profile": name,
            "profile_dir": str(data_dir),
            "screenshot_path": str(target) if image else "",
            "bytes": len(image),
        }
    if action in {"click", "type", "fill", "press", "select", "scroll", "submit", "purchase", "login"}:
        transport.send(
            "Runtime.evaluate",
            {
                "expression": "true",
                "action": action,
                "selector": str(tool_input.get("selector") or ""),
                "text": str(tool_input.get("text") or ""),
            },
        )
        return {"action": action, "profile": name, "profile_dir": str(data_dir), "ok": True}
    if action in {"go_back", "reload", "wait", "list_tabs", "new_tab", "close_tab"}:
        transport.send("Runtime.evaluate", {"expression": action})
        return {"action": action, "profile": name, "profile_dir": str(data_dir), "ok": True}
    raise BrowserError(f"Unknown browser action {action!r}.")


def _eval_text(transport: BrowserTransport, expression: str) -> str:
    result = transport.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    value = result.get("result", result)
    if isinstance(value, dict):
        inner = value.get("value")
        return inner if isinstance(inner, str) else ""
    return value if isinstance(value, str) else ""
