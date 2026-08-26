"""Agent-facing Procoder engineering gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.install.record import resolve_source_dir
from src.integrations.procoder import ProcoderManager

from ..context import ToolContext
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class ProcoderTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(name="Procoder", description=("Run the checksum-verified local engineering gate: honest code checks, repository tests, security/audit/release reports, and optional code indexing. It never edits, commits, tags, files issues, or installs hooks."),
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["status", "sync", "install", "doctor", "check", "test", "audit", "security", "git", "docs", "ci", "infra", "maintain", "deps", "release", "index"]},
                "argument": {"type": "string", "enum": ["", "build", "stats", "entrypoints", "impact", "unused", "graph"]},
                "deep": {"type": "boolean"}, "coverage": {"type": "boolean"},
                "timeout": {"type": "integer", "minimum": 30, "maximum": 3600},
            }, "required": ["action"]}, is_destructive=True, max_result_size_chars=100_000, strict=True)

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in {"status", "doctor"}:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "Procoder", "Run repository quality tools or update the isolated controller",
                                        "Allow Procoder quality checks for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        manager = ProcoderManager(resolve_source_dir() or Path.cwd())
        output = manager.execute(str(tool_input["action"]), workspace=context.workspace_root,
                                 argument=str(tool_input.get("argument") or ""), deep=bool(tool_input.get("deep")),
                                 coverage=bool(tool_input.get("coverage")), timeout=int(tool_input.get("timeout") or 1800))
        return ToolResult(name="Procoder", output=output, is_error=output.get("ok") is False)
