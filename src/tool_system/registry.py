from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol

from .context import ToolContext
from .permission_handler import PermissionResult
from .protocol import ToolCall, ToolResult
from .schema_validation import validate_json_schema


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    aliases: tuple[str, ...] = ()
    is_read_only: bool = False
    is_destructive: bool = False
    strict: bool = False
    max_result_size_chars: int = 20_000


class Tool(Protocol):
    def spec(self) -> ToolSpec: ...

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult: ...

    def check_permissions(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> PermissionResult:
        """Check if this tool has permission to run.

        Args:
            tool_input: The input arguments for the tool.
            context: The tool execution context.

        Returns:
            PermissionResult indicating allow, deny, or ask.
        """
        return PermissionResult.allow()


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: list[Tool] = []
        self._by_name: dict[str, Tool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        spec = tool.spec()
        key = spec.name.lower()
        if key in self._by_name:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._tools.append(tool)
        self._by_name[key] = tool
        for alias in spec.aliases:
            alias_key = alias.lower()
            if alias_key in self._by_name:
                raise ValueError(f"duplicate tool alias: {alias}")
            self._by_name[alias_key] = tool

    def list_specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools]

    def get(self, name: str) -> Tool | None:
        return self._by_name.get(name.lower())

    def dispatch(self, call: ToolCall, context: ToolContext) -> ToolResult:
        started = datetime.now(timezone.utc)

        def audited(result: ToolResult, *, permission: str = "allowed") -> ToolResult:
            if context.audit_logger is not None:
                context.audit_logger({
                    "session_id": context.session_id or "",
                    "tool": result.name or call.name,
                    "tool_use_id": call.tool_use_id or "",
                    "input": call.input,
                    "permission": permission,
                    "status": "error" if result.is_error else "success",
                    "duration_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 3),
                    "result_summary": str(result.output)[:1000],
                })
            return result

        tool = self.get(call.name)
        if tool is None:
            return audited(ToolResult(
                name=call.name,
                output={"error": f"unknown tool: {call.name}"},
                is_error=True,
                tool_use_id=call.tool_use_id,
            ))
        spec = tool.spec()
        context.ensure_tool_allowed(spec.name)
        validate_json_schema(call.input, spec.input_schema, root_name=spec.name)

        # Check permissions before running
        permission_result = tool.check_permissions(call.input, context) if hasattr(tool, 'check_permissions') else PermissionResult.allow()
        if permission_result.behavior.value == "deny":
            return audited(ToolResult(
                name=spec.name,
                output={"error": permission_result.message or "permission denied"},
                is_error=True,
                tool_use_id=call.tool_use_id,
            ), permission="denied")
        if permission_result.behavior.value == "ask":
            # Need user interaction
            if context.permission_handler is None:
                # No handler available, deny by default
                return audited(ToolResult(
                    name=spec.name,
                    output={"error": permission_result.message or "permission required but no handler available"},
                    is_error=True,
                    tool_use_id=call.tool_use_id,
                ), permission="required")
            # Call the permission handler
            allowed, _ = context.permission_handler(
                spec.name,
                permission_result.message or f"Tool '{spec.name}' requires permission",
                permission_result.suggestion,
            )
            if not allowed:
                return audited(ToolResult(
                    name=spec.name,
                    output={"error": "permission denied by user"},
                    is_error=True,
                    tool_use_id=call.tool_use_id,
                ), permission="denied")
            # User allowed - proceed with potentially updated input
            if permission_result.updated_input:
                call = ToolCall(
                    name=call.name,
                    input=permission_result.updated_input,
                    tool_use_id=call.tool_use_id,
                )

        # Persist the approved intent before any side effect begins. The audit
        # logger is part of the enforcement path: if its write fails, dispatch
        # fails closed and the tool is not run. A second record below captures
        # the actual result or exception.
        if context.audit_logger is not None:
            context.audit_logger({
                "session_id": context.session_id or "",
                "tool": spec.name,
                "tool_use_id": call.tool_use_id or "",
                "input": call.input,
                "permission": "approved",
                "status": "started",
                "duration_ms": 0,
                "result_summary": "Approved action recorded before execution",
            })

        try:
            result = tool.run(call.input, context)
        except Exception as exc:
            if context.audit_logger is not None:
                context.audit_logger({
                    "session_id": context.session_id or "",
                    "tool": spec.name,
                    "tool_use_id": call.tool_use_id or "",
                    "input": call.input,
                    "permission": "allowed",
                    "status": "exception",
                    "duration_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 3),
                    "result_summary": f"{type(exc).__name__}: {exc}"[:1000],
                })
            raise
        if result.tool_use_id is None and call.tool_use_id is not None:
            return audited(ToolResult(
                name=result.name,
                output=result.output,
                is_error=result.is_error,
                tool_use_id=call.tool_use_id,
                content_type=result.content_type,
            ))
        return audited(result)

