from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _validate_host(value: object) -> str:
    host = str(value or "").strip()
    if not host or len(host) > 253 or any(char in host for char in "\x00\r\n /\\@"):
        raise ToolInputError("host must be an IP address or DNS hostname")
    unwrapped = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(unwrapped.split("%", 1)[0])
        return unwrapped
    except ValueError:
        pass
    if not all(_HOST_LABEL.fullmatch(label) for label in host.rstrip(".").split(".")):
        raise ToolInputError("host must be an IP address or DNS hostname")
    return host.rstrip(".")


def _bounded_text(value: str, limit: int = 30_000) -> str:
    return value if len(value) <= limit else value[:limit] + "\n...[truncated]"


class RemoteTriggerTool:
    """Permission-gated remote administration through installed OS clients."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="RemoteTrigger",
            description=(
                "Probe or administer an explicitly named computer/server through SSH, SCP, or Windows Remote Management. "
                "Uses existing SSH keys, ssh-agent, or stored Windows credentials; passwords are never accepted in tool input. "
                "The remote service and account must already be authorized by that computer."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["capabilities", "probe", "run", "upload", "download"]},
                    "transport": {"type": "string", "enum": ["ssh", "winrm"]},
                    "host": {"type": "string"},
                    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                    "user": {"type": "string"},
                    "command": {"type": "string"},
                    "local_path": {"type": "string"},
                    "remote_path": {"type": "string"},
                    "identity_file": {"type": "string"},
                    "host_key_policy": {"type": "string", "enum": ["strict", "accept-new"]},
                    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 3600},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=70_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "")
        host = str(tool_input.get("host") or "this computer")
        return maybe_ask_for_gated_tool(
            context,
            "RemoteTrigger",
            f"Run remote action '{action}' on {host}",
            "Allow RemoteTrigger for the rest of this conversation",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input.get("action") or "")
        if action == "capabilities":
            return ToolResult(name="RemoteTrigger", output={
                "ssh": shutil.which("ssh"),
                "scp": shutil.which("scp"),
                "winrm": shutil.which("winrs") if os.name == "nt" else None,
                "actions": ["probe", "run", "upload", "download"],
                "authentication": "existing SSH key/agent or stored Windows credentials",
                "password_input_supported": False,
                "approval_required": True,
            })

        host = _validate_host(tool_input.get("host"))
        transport = str(tool_input.get("transport") or "ssh")
        port = int(tool_input.get("port") or (22 if transport == "ssh" else 5985))
        timeout = int(tool_input.get("timeout_s") or 60)
        if action == "probe":
            return self._probe(host, port, timeout)
        if action == "run":
            return self._run_command(tool_input, context, host, transport, port, timeout)
        if action in {"upload", "download"}:
            if transport != "ssh":
                raise ToolInputError("file transfer currently requires transport=ssh (SCP)")
            return self._transfer(action, tool_input, context, host, port, timeout)
        raise ToolInputError(f"unsupported remote action: {action}")

    @staticmethod
    def _probe(host: str, port: int, timeout: int) -> ToolResult:
        try:
            with socket.create_connection((host, port), timeout=min(timeout, 15)) as connection:
                peer = connection.getpeername()
            return ToolResult(name="RemoteTrigger", output={"host": host, "port": port, "reachable": True, "peer": str(peer)})
        except OSError as exc:
            return ToolResult(name="RemoteTrigger", output={"host": host, "port": port, "reachable": False, "error": str(exc)}, is_error=True)

    @staticmethod
    def _identity_args(tool_input: dict[str, Any], context: ToolContext) -> list[str]:
        raw = str(tool_input.get("identity_file") or "").strip()
        if not raw:
            return []
        identity = context.ensure_allowed_path(raw)
        if not identity.is_file():
            raise ToolInputError(f"SSH identity file does not exist: {identity}")
        return ["-i", str(identity)]

    @classmethod
    def _ssh_options(cls, tool_input: dict[str, Any], context: ToolContext, timeout: int) -> list[str]:
        policy = str(tool_input.get("host_key_policy") or "strict")
        strict_value = "accept-new" if policy == "accept-new" else "yes"
        return [
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={min(timeout, 60)}",
            "-o", f"StrictHostKeyChecking={strict_value}",
            *cls._identity_args(tool_input, context),
        ]

    @staticmethod
    def _destination(host: str, user: object) -> str:
        username = str(user or "").strip()
        if username and (not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username)):
            raise ToolInputError("user contains unsupported characters")
        wrapped = f"[{host}]" if ":" in host else host
        return f"{username}@{wrapped}" if username else wrapped

    @classmethod
    def _run_command(
        cls,
        tool_input: dict[str, Any],
        context: ToolContext,
        host: str,
        transport: str,
        port: int,
        timeout: int,
    ) -> ToolResult:
        command = str(tool_input.get("command") or "")
        if not command.strip() or "\x00" in command:
            raise ToolInputError("command must be a non-empty string without NUL bytes")
        if transport == "ssh":
            executable = shutil.which("ssh")
            if not executable:
                raise ToolExecutionError("OpenSSH client is not installed")
            args = [
                executable,
                *cls._ssh_options(tool_input, context, timeout),
                "-p", str(port),
                cls._destination(host, tool_input.get("user")),
                command,
            ]
        else:
            executable = shutil.which("winrs") if os.name == "nt" else None
            if not executable:
                raise ToolExecutionError("Windows Remote Management client (winrs) is not installed")
            endpoint = f"http{'s' if port == 5986 else ''}://{host}:{port}"
            args = [executable, f"-r:{endpoint}"]
            user = str(tool_input.get("user") or "").strip()
            if user:
                args.append(f"-u:{user}")
            args.append(command)
        return cls._execute(args, host, transport, timeout, action="run")

    @classmethod
    def _transfer(
        cls,
        action: str,
        tool_input: dict[str, Any],
        context: ToolContext,
        host: str,
        port: int,
        timeout: int,
    ) -> ToolResult:
        executable = shutil.which("scp")
        if not executable:
            raise ToolExecutionError("SCP client is not installed")
        local_raw = str(tool_input.get("local_path") or "").strip()
        remote = str(tool_input.get("remote_path") or "").strip()
        if not local_raw or not remote or any(char in remote for char in "\x00\r\n"):
            raise ToolInputError("local_path and a single-line remote_path are required")
        local = context.ensure_allowed_path(local_raw)
        if action == "upload" and not local.is_file():
            raise ToolInputError(f"upload source is not a file: {local}")
        if action == "download":
            local.parent.mkdir(parents=True, exist_ok=True)
        remote_spec = f"{cls._destination(host, tool_input.get('user'))}:{remote}"
        source, destination = (str(local), remote_spec) if action == "upload" else (remote_spec, str(local))
        args = [
            executable,
            *cls._ssh_options(tool_input, context, timeout),
            "-P", str(port),
            source,
            destination,
        ]
        result = cls._execute(args, host, "scp", timeout, action=action)
        if action == "download" and local.is_file() and not result.is_error:
            result.output["local_path"] = str(local)
            result.output["size"] = local.stat().st_size
        return result

    @staticmethod
    def _execute(args: list[str], host: str, transport: str, timeout: int, *, action: str) -> ToolResult:
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError(f"remote {action} timed out after {timeout} seconds") from exc
        except OSError as exc:
            raise ToolExecutionError(str(exc)) from exc
        output = {
            "action": action,
            "host": host,
            "transport": transport,
            "exit_code": completed.returncode,
            "stdout": _bounded_text(completed.stdout or ""),
            "stderr": _bounded_text(completed.stderr or ""),
        }
        return ToolResult(name="RemoteTrigger", output=output, is_error=completed.returncode != 0)
