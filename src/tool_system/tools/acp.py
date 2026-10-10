"""Delegate a coding task to a local ACP runner."""

from __future__ import annotations

import shlex
from typing import Any

from src.acp.runners import RUNNER_LABELS, load_runners
from src.acp.service import delegate_task, resolve_folder, runner_argv
from src.security.shell_guard import enforce_shell_command, shell_command_permission

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionBehavior, PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class AcpTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Acp",
            description=(
                "Delegate a coding task to a local ACP runner (OpenCode, Claude Code, "
                "Codex, or Zed) in a chosen project folder. Streams progress and lists "
                "changed files. The runner command and the folder require approval, "
                "and the shell guard still applies. Runners are enabled in settings."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "runner": {
                        "type": "string",
                        "description": "opencode, claude_code, codex, or zed",
                    },
                    "folder": {
                        "type": "string",
                        "description": "Existing project folder for the runner",
                    },
                    "task": {"type": "string", "description": "Coding task to delegate"},
                    "command": {
                        "type": "string",
                        "description": "Resolved runner command. Filled by the approval check.",
                    },
                },
                "required": ["runner", "folder", "task"],
            },
            is_destructive=True,
            max_result_size_chars=50_000,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        try:
            prepared = _prepare(tool_input, context)
        except (ToolInputError, ValueError) as exc:
            return PermissionResult.deny(str(exc))
        payload = dict(tool_input)
        payload["command"] = prepared["command_line"]
        guarded = shell_command_permission("Acp", prepared["command_line"], context)
        if guarded is not None:
            if guarded.behavior == PermissionBehavior.DENY:
                return guarded
            message = f"Project folder: {prepared['folder']}\n{guarded.message}"
            return PermissionResult(
                behavior=guarded.behavior,
                message=message,
                suggestion=guarded.suggestion or "Approve this runner command once",
                updated_input=payload,
            )
        asked = maybe_ask_for_gated_tool(
            context,
            "Acp",
            (
                f"Delegate to {prepared['label']} in {prepared['folder']}. "
                f"Command: {prepared['command_line']}"
            ),
            "Allow ACP runners for the rest of this session",
        )
        if asked.behavior == PermissionBehavior.ASK:
            return PermissionResult(
                behavior=PermissionBehavior.ASK,
                message=asked.message,
                suggestion=asked.suggestion,
                updated_input=payload,
            )
        return PermissionResult.allow(updated_input=payload)

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            prepared = _prepare(tool_input, context)
        except (ToolInputError, ValueError) as exc:
            return ToolResult(name="Acp", output={"error": str(exc)}, is_error=True)
        command_line = str(tool_input.get("command") or prepared["command_line"])
        try:
            enforce_shell_command("Acp", command_line, context)
        except ToolPermissionError as exc:
            return ToolResult(name="Acp", output={"error": str(exc)}, is_error=True)
        progress = getattr(context, "progress_handler", None)

        def on_progress(line: str) -> None:
            if callable(progress):
                progress(line)

        try:
            text = delegate_task(
                runner_id=prepared["runner"],
                folder=str(prepared["folder"]),
                task=prepared["task"],
                directory=getattr(context, "acp_dir", None),
                on_progress=on_progress,
                context=context,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return ToolResult(name="Acp", output={"error": str(exc)}, is_error=True)
        return ToolResult(name="Acp", output={"text": text, "folder": str(prepared["folder"])})


def _prepare(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    runner_id = tool_input.get("runner")
    folder = tool_input.get("folder")
    task = tool_input.get("task")
    if not isinstance(runner_id, str) or not runner_id.strip():
        raise ToolInputError("runner is required")
    if not isinstance(folder, str):
        raise ToolInputError("folder is required")
    if not isinstance(task, str) or not task.strip():
        raise ToolInputError("task is required")
    runners = load_runners(getattr(context, "acp_dir", None))
    if runner_id.strip() not in runners:
        raise ToolInputError(f"unknown ACP runner: {runner_id.strip()}")
    config = runners[runner_id.strip()]
    if not config.enabled:
        label = RUNNER_LABELS[runner_id.strip()]
        raise ValueError(f"{label} is not enabled. Turn it on in settings and set its path.")
    project = resolve_folder(folder)
    argv = runner_argv(config)
    return {
        "runner": runner_id.strip(),
        "label": RUNNER_LABELS[runner_id.strip()],
        "folder": project,
        "task": task.strip(),
        "command_line": shlex.join(argv),
    }
