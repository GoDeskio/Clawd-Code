from __future__ import annotations

import json
from typing import Any

from src.agent.memory import add_fact, list_conversation_index, list_facts

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class SharedMemoryTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="SharedMemory",
            description=(
                "Recall, search, explicitly remember, or export durable memory shared across all conversations. "
                "Full chat session files remain separate; this provides searchable facts and conversation summaries."
            ),
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["recall", "search", "remember", "export"]},
                    "query": {"type": "string"}, "text": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000}, "output": {"type": "string"}
                },
                "required": ["action"]
            },
            is_destructive=True, max_result_size_chars=100_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in {"recall", "search"}:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "SharedMemory", f"{tool_input.get('action')} durable shared memory",
                                        "Allow shared-memory changes for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        limit = int(tool_input.get("limit") or 200)
        facts = list_facts()
        conversations = list_conversation_index()
        if action == "remember":
            text = str(tool_input.get("text") or "").strip()
            if not text:
                raise ToolInputError("text is required for remember")
            item = add_fact(text, source_session=context.session_id or "")
            return ToolResult(name="SharedMemory", output={"remembered": item})
        if action == "search":
            query = str(tool_input.get("query") or "").strip().lower()
            if not query:
                raise ToolInputError("query is required for search")
            matched_facts = [item for item in facts if query in str(item.get("text") or "").lower()]
            matched_conversations = [item for item in conversations if query in (str(item.get("title") or "") + " " + str(item.get("summary") or "")).lower()]
            return ToolResult(name="SharedMemory", output={"query": query, "facts": matched_facts[:limit], "conversations": matched_conversations[:limit]})
        if action == "recall":
            return ToolResult(name="SharedMemory", output={"facts": facts[-limit:], "conversations": conversations[:limit],
                "note": "Full messages remain in persistent session JSON and are available through conversation instances."})
        if action == "export":
            output = context.ensure_allowed_path(str(tool_input.get("output") or "memory/jonathan-memory.json"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"facts": facts, "conversations": conversations}, indent=2, ensure_ascii=False), encoding="utf-8")
            artifacts = [context.artifact_publisher(output, output.name)] if context.artifact_publisher else []
            return ToolResult(name="SharedMemory", output={"path": str(output), "fact_count": len(facts),
                "conversation_count": len(conversations), "artifact": artifacts[0] if artifacts else None, "artifacts": artifacts})
        raise ToolInputError(f"unsupported memory action: {action}")
