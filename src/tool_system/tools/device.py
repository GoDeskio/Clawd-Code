"""Approval-gated control of a registered LAN device."""

from __future__ import annotations

from typing import Any

from src.devices.control import approval_key, perform_action
from src.devices.lan import WanTargetError, require_private_host
from src.devices.registry import get_device
from src.security.shell_guard import enforce_shell_command, shell_command_permission

from ..context import ToolContext
from ..errors import ToolPermissionError
from ..permission_handler import PermissionBehavior, PermissionResult
from ..protocol import ToolResult
from ..registry import ToolSpec


class DeviceTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Device",
            description=(
                "Run one allow-listed action on a registered LAN device "
                "(MQTT, Home Assistant, HTTP, or SSH). Every action asks for "
                "approval. Public and WAN addresses are refused."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "device": {"type": "string", "description": "Registered device id"},
                    "action": {"type": "string", "description": "Allow-listed action name"},
                    "command": {
                        "type": "string",
                        "description": "Approval key filled by the permission check",
                    },
                },
                "required": ["device", "action"],
            },
            is_destructive=True,
            max_result_size_chars=20_000,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        try:
            device, action, key = _prepare(tool_input, context)
        except (ValueError, WanTargetError) as exc:
            return PermissionResult.deny(str(exc))
        payload = dict(tool_input)
        payload["command"] = key
        guarded = shell_command_permission("Device", key, context)
        if guarded is not None and guarded.behavior == PermissionBehavior.DENY:
            return guarded
        if key in getattr(context, "approved_shell_commands", set()):
            return PermissionResult.allow(updated_input=payload)
        message = f"Control {device['kind']} {device['id']} at {device['host']}: {action}"
        if guarded is not None and guarded.message:
            message = f"{message}\n{guarded.message}"
        return PermissionResult(
            behavior=PermissionBehavior.ASK,
            message=message,
            suggestion="Approve this device action once",
            updated_input=payload,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            device, action, key = _prepare(tool_input, context)
        except (ValueError, WanTargetError) as exc:
            return ToolResult(name="Device", output={"error": str(exc)}, is_error=True)
        if key not in getattr(context, "approved_shell_commands", set()):
            return ToolResult(
                name="Device",
                output={"error": "device action requires approval"},
                is_error=True,
            )
        try:
            enforce_shell_command("Device", key, context)
        except ToolPermissionError as exc:
            return ToolResult(name="Device", output={"error": str(exc)}, is_error=True)
        try:
            text = perform_action(
                device,
                action,
                directory=getattr(context, "devices_dir", None),
                user_id=_user(context),
                poster=getattr(context, "device_poster", None),
                tcp_send=getattr(context, "device_tcp", None),
                ssh_runner=getattr(context, "device_ssh", None),
            )
        except (ValueError, WanTargetError, OSError, RuntimeError) as exc:
            return ToolResult(name="Device", output={"error": str(exc)}, is_error=True)
        return ToolResult(name="Device", output={"text": text, "device": device["id"], "action": action})


def _prepare(tool_input: dict[str, Any], context: ToolContext) -> tuple[dict, str, str]:
    device_id = tool_input.get("device")
    action = tool_input.get("action")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("device is required")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("action is required")
    device = get_device(device_id.strip(), getattr(context, "devices_dir", None))
    cleaned = action.strip()
    require_private_host(str(device.get("host") or ""))
    if cleaned not in list(device.get("actions") or []):
        raise ValueError(f"action {cleaned!r} is not on the allow-list for {device.get('id')}")
    key = approval_key(device["id"], cleaned)
    return device, cleaned, key


def _user(context: ToolContext) -> str:
    from src.agent.memory import current_user_id

    return current_user_id()
