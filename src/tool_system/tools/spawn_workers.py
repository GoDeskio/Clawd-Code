from __future__ import annotations

from typing import Any

from src.agent.multi_agent import run_internal_workers

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


class SpawnWorkersTool:
    """Let the main agent fan a goal out to isolated internal workers."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="SpawnWorkers",
            description=(
                "Plan a goal into isolated Jonathan Ai workers and run them in parallel. "
                "Workers share memory notes only — they do not merge chats. "
                "Does not require MCP, Cursor, or Codex."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "workers": {"type": "integer"},
                },
                "required": ["goal"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        goal = tool_input.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise ToolInputError("goal must be a non-empty string")
        raw_count = tool_input.get("workers") or 3
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 3
        provider = getattr(context, "provider", None)
        if provider is None:
            return ToolResult(
                name="SpawnWorkers",
                output={"error": "No provider on this context. Send the goal from the Workers button."},
                is_error=True,
            )
        result = run_internal_workers(
            provider=provider,
            goal=goal.strip(),
            parent_session_id=getattr(context, "session_id", "") or "",
            max_workers=count,
        )
        return ToolResult(name="SpawnWorkers", output=result)
