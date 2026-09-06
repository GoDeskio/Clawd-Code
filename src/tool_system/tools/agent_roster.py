from __future__ import annotations

from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class AgentRosterTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="AgentRoster",
            description="List persistent named agents, read an agent inbox, or send work to another named agent.",
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "inbox", "send", "run"]},
                    "agent_id": {"type": "string"},
                    "message": {"type": "string"},
                    "mark_read": {"type": "boolean"},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=80_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in {"list", "inbox"}:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "AgentRoster", "Send a message or task to another named agent", "Allow agent-to-agent work for this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.agent_roster is None:
            return ToolResult(name="AgentRoster", output={"error": "named agents are unavailable in this host"}, is_error=True)
        action = str(tool_input.get("action") or "")
        if action not in {"list", "inbox", "send", "run"}:
            raise ToolInputError("unsupported roster action")
        agent_id = str(tool_input.get("agent_id") or "")
        if action != "list" and not agent_id:
            raise ToolInputError("agent_id is required")
        if action in {"send", "run"} and not str(tool_input.get("message") or "").strip():
            raise ToolInputError("message is required")
        output = context.agent_roster(action, {
            "agent_id": agent_id,
            "message": str(tool_input.get("message") or ""),
            "mark_read": bool(tool_input.get("mark_read")),
        })
        return ToolResult(name="AgentRoster", output=output)

