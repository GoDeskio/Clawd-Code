"""Agent-facing local code graph and durable memory tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.install.record import resolve_source_dir
from src.integrations.claude_db import ClaudeDbManager

from ..context import ToolContext
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class CodeMemoryTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CodeMemory",
            description=("Search live text or use a local incremental code graph to explain symbols, find usages and dependency paths. "
                         "Can store an explicitly requested durable note. Uses local SQLite; installs no Claude hooks."),
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["status", "sync", "install", "scan", "search", "remember", "usages", "explain", "path"]},
                "query": {"type": "string"}, "target": {"type": "string"},
                "mode": {"type": "string", "enum": ["text", "usages", "explain", "path"]},
                "force": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            }, "required": ["action"]},
            is_destructive=True, max_result_size_chars=50_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in {"status", "search", "usages", "explain", "path"}:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "CodeMemory", "Install/update the local engine or write its local graph/memory database",
                                        "Allow local code-memory writes for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        manager = ClaudeDbManager(resolve_source_dir() or Path.cwd())
        output = manager.execute(str(tool_input["action"]), workspace=context.workspace_root,
                                 query=str(tool_input.get("query") or ""), target=str(tool_input.get("target") or ""),
                                 mode=str(tool_input.get("mode") or "text"), force=bool(tool_input.get("force")),
                                 limit=int(tool_input.get("limit") or 100))
        return ToolResult(name="CodeMemory", output=output)
