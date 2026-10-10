"""Browser tool: CDP control of Chrome with a profile that keeps logins."""

from __future__ import annotations

from typing import Any

from ...browser.actions import check_browser_permission, run_browser_action
from ...browser.sources import BrowserError
from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..protocol import ToolResult
from ..registry import ToolSpec


class BrowserTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Browser",
            description=(
                "Control a local Chrome or Chromium window over the DevTools Protocol. "
                "The profile directory is kept so logins persist. Form submits, purchases, "
                "and logins each need approval. Browser downloads use Chrome for Testing "
                "or the official Playwright CDN."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string"},
                    "url": {"type": "string"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "profile": {"type": "string"},
                },
                "required": ["action"],
            },
            is_read_only=False,
            is_destructive=True,
            max_result_size_chars=20_000,
        )

    def check_permissions(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> PermissionResult:
        if not isinstance(tool_input, dict) or not str(tool_input.get("action") or "").strip():
            return PermissionResult.deny(message="Browser action is required.")
        return check_browser_permission(tool_input, context)

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = tool_input.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ToolInputError("action must be a non-empty string")
        transport = getattr(context, "browser_transport", None)
        if transport is None or not hasattr(transport, "send") or not hasattr(transport, "connect"):
            raise BrowserError(
                "No browser transport is attached. Connect local Chrome before running Browser."
            )
        try:
            output = run_browser_action(
                tool_input,
                transport=transport,
                profile_root=getattr(context, "browser_profile_root", None),
            )
        except BrowserError as exc:
            raise ToolInputError(str(exc)) from exc
        return ToolResult(name="Browser", output=output)
