from __future__ import annotations

from typing import Any

from src.connectors.agents import get_saved_agent, invoke_agent

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


class ExternalAgentTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ExternalAgent",
            description="Invoke an OpenAI-compatible agent the user connected in settings (Cursor/Codex/local hook or a URL they added).",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["name", "text"],
            },
            is_destructive=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        name = tool_input.get("name")
        text = tool_input.get("text")
        if not isinstance(name, str) or not name.strip():
            raise ToolInputError("name must be a connected agent")
        if not isinstance(text, str) or not text.strip():
            raise ToolInputError("text is required")
        saved = get_saved_agent(name)
        if not saved.get("enabled", True):
            return ToolResult(name="ExternalAgent", output={"error": f"agent disabled: {name}"}, is_error=True)
        out = invoke_agent(str(saved.get("base_url") or ""), text, api_key=str(saved.get("api_key") or ""))
        return ToolResult(name="ExternalAgent", output=out)
