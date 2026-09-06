from __future__ import annotations

from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


class AgentInstancesTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="AgentInstances",
            description="List other conversation agents or read one agent's visible transcript when cross-instance context is needed.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "read"]},
                    "session_id": {"type": "string"},
                },
                "required": ["action"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.instance_reader is None:
            return ToolResult(name="AgentInstances", output={"error": "cross-instance viewing is unavailable in this host"}, is_error=True)
        action = str(tool_input.get("action") or "").lower()
        if action not in {"list", "read"}:
            raise ToolInputError("action must be list or read")
        session_id = str(tool_input.get("session_id") or "")
        if action == "read" and not session_id:
            raise ToolInputError("session_id is required for read")
        return ToolResult(name="AgentInstances", output=context.instance_reader(action, session_id))
