"""SQLite-backed scheduler tools.

Replaces the in-memory cron list. Jobs persist per user, default to
America/Phoenix, and run as either a fixed text message or an agent task.
"""

from __future__ import annotations

from typing import Any

from ...scheduler.service import (
    create_job,
    delete_job,
    list_jobs,
    list_logs,
    run_now,
    set_enabled,
)
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec

_SCHEDULE_HELP = (
    "Unix 5-field cron (minute hour day month weekday), "
    "or interval:<seconds>, or date:<ISO-8601>. "
    "Times use America/Phoenix unless timezone is set."
)


def _value_error(exc: ValueError) -> ToolInputError:
    return ToolInputError(str(exc))


class CronCreateTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronCreate",
            description=(
                "Schedule a persistent job in the local SQLite scheduler. "
                "task_type 'text' delivers the prompt as a message. "
                "task_type 'agent' runs the prompt with the same approvals and shell guard. "
                + _SCHEDULE_HELP
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "cron": {"type": "string", "description": _SCHEDULE_HELP},
                    "prompt": {"type": "string"},
                    "task_type": {"type": "string", "description": "text or agent. Default text."},
                    "name": {"type": "string"},
                    "recurring": {"type": "boolean"},
                    "durable": {"type": "boolean"},
                    "enabled": {"type": "boolean"},
                    "timezone": {"type": "string"},
                },
                "required": ["cron", "prompt"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        cron = tool_input.get("cron")
        prompt = tool_input.get("prompt")
        if not isinstance(cron, str) or not cron.strip():
            raise ToolInputError("cron must be a non-empty string")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ToolInputError("prompt must be a non-empty string")
        try:
            job = create_job(
                context,
                cron=cron,
                prompt=prompt,
                task_type=str(tool_input.get("task_type") or "text"),
                name=tool_input.get("name") if isinstance(tool_input.get("name"), str) else None,
                enabled=bool(tool_input.get("enabled", True)),
                recurring=bool(tool_input["recurring"]) if "recurring" in tool_input else None,
                timezone_name=tool_input.get("timezone") if isinstance(tool_input.get("timezone"), str) else None,
            )
        except ValueError as exc:
            raise _value_error(exc) from exc
        return ToolResult(name="CronCreate", output=job)


class CronListTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronList",
            description="List scheduled jobs stored for this user.",
            input_schema={"type": "object", "additionalProperties": False, "properties": {}},
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        del tool_input
        return ToolResult(name="CronList", output={"jobs": list_jobs(context)})


class CronDeleteTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronDelete",
            description="Delete a scheduled job for this user.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        cid = tool_input.get("id")
        if not isinstance(cid, str) or not cid.strip():
            raise ToolInputError("id must be a non-empty string")
        existed = delete_job(context, cid)
        return ToolResult(name="CronDelete", output={"success": existed, "id": cid})


class CronEnableTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronEnable",
            description="Enable a scheduled job.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(name="CronEnable", output=_set(context, tool_input, True))


class CronDisableTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronDisable",
            description="Disable a scheduled job without deleting it.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(name="CronDisable", output=_set(context, tool_input, False))


class CronRunNowTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronRunNow",
            description="Run one scheduled job immediately.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        cid = tool_input.get("id")
        if not isinstance(cid, str) or not cid.strip():
            raise ToolInputError("id must be a non-empty string")
        try:
            result = run_now(context, cid)
        except KeyError as exc:
            raise ToolInputError(f"No job with id {exc.args[0]} for this user.") from exc
        except ValueError as exc:
            raise _value_error(exc) from exc
        return ToolResult(name="CronRunNow", output=result)


class CronLogsTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="CronLogs",
            description="Show recent scheduler logs for this user.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}},
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        job_id = tool_input.get("id")
        if job_id is not None and not isinstance(job_id, str):
            raise ToolInputError("id must be a string")
        return ToolResult(
            name="CronLogs",
            output={"logs": list_logs(context, job_id.strip() if isinstance(job_id, str) and job_id.strip() else None)},
        )


def _set(context: ToolContext, tool_input: dict[str, Any], enabled: bool) -> dict[str, Any]:
    cid = tool_input.get("id")
    if not isinstance(cid, str) or not cid.strip():
        raise ToolInputError("id must be a non-empty string")
    try:
        return set_enabled(context, cid, enabled)
    except KeyError as exc:
        raise ToolInputError(f"No job with id {exc.args[0]} for this user.") from exc
