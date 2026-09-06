from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec
from .bash import _DANGEROUS_PATTERNS, _truncate


_SHELL_NAMES = ("pwsh", "powershell", "cmd", "bash", "sh", "zsh", "fish", "wsl", "nu", "xonsh")


def discover_terminals() -> list[dict[str, str]]:
    """Return installed command shells without executing them."""
    found: dict[str, str] = {}
    for name in _SHELL_NAMES:
        executable = shutil.which(name)
        if executable:
            found[name] = str(Path(executable).resolve())
    if os.name == "nt":
        candidates = {
            "git-bash": [
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
                Path(os.environ.get("LocalAppData", "")) / "Programs" / "Git" / "bin" / "bash.exe",
            ],
            "cmd": [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"],
            "powershell": [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"],
        }
        for name, paths in candidates.items():
            if name in found:
                continue
            match = next((path for path in paths if str(path) and path.is_file()), None)
            if match:
                found[name] = str(match.resolve())
    return [{"name": name, "path": path} for name, path in found.items()]


def _resolve_shell(requested: str) -> tuple[str, Path]:
    available = {item["name"].lower(): Path(item["path"]) for item in discover_terminals()}
    name = str(requested or "auto").strip().lower()
    if name == "auto":
        preference = ("pwsh", "powershell", "cmd", "git-bash", "bash") if os.name == "nt" else ("bash", "zsh", "fish", "sh", "pwsh")
        for candidate in preference:
            if candidate in available:
                return candidate, available[candidate]
        raise ToolInputError("no supported command shell was found on PATH")
    if name in available:
        return name, available[name]
    candidate = Path(str(requested)).expanduser()
    if candidate.is_absolute() and candidate.is_file():
        return candidate.stem.lower(), candidate.resolve()
    raise ToolInputError(f"shell is not installed or was not found: {requested}")


def _command_args(shell_name: str, executable: Path, command: str) -> list[str]:
    lowered = executable.name.lower()
    if shell_name in {"pwsh", "powershell"} or "powershell" in lowered or lowered == "pwsh.exe":
        return [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    if shell_name == "cmd" or lowered == "cmd.exe":
        return [str(executable), "/d", "/s", "/c", command]
    if shell_name == "wsl" or lowered == "wsl.exe":
        return [str(executable), "--", "bash", "-lc", command]
    if shell_name in {"nu", "nushell"} or lowered in {"nu", "nu.exe"}:
        return [str(executable), "-c", command]
    return [str(executable), "-lc", command]


def run_terminal_command(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ToolInputError("command must be a non-empty string")
    if "\x00" in command:
        raise ToolInputError("command contains NUL byte")
    if not context.permission_context.full_system_access:
        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(command):
                raise ToolPermissionError("refusing to run potentially dangerous command without Full Device & Network Access")

    raw_cwd = tool_input.get("cwd")
    cwd = context.ensure_allowed_path(raw_cwd) if raw_cwd else (context.cwd or context.workspace_root)
    if not cwd.is_dir():
        raise ToolInputError(f"cwd is not a directory: {cwd}")
    timeout_s = tool_input.get("timeout_s", 60)
    if not isinstance(timeout_s, int) or timeout_s < 1 or timeout_s > 600:
        raise ToolInputError("timeout_s must be an integer between 1 and 600")
    shell_name, executable = _resolve_shell(str(tool_input.get("shell") or "auto"))
    completed = subprocess.run(
        _command_args(shell_name, executable, command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=os.environ.copy(),
    )
    return {
        "shell": shell_name,
        "executable": str(executable),
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout": _truncate(completed.stdout or ""),
        "stderr": _truncate(completed.stderr or ""),
    }


class TerminalTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Terminal",
            description="Run a command through any installed shell (PowerShell, cmd, Bash, WSL, zsh, fish, nushell, or an explicit shell executable). Installed CLIs are inherited from the computer PATH.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "command": {"type": "string"},
                    "shell": {"type": "string", "description": "auto, pwsh, powershell, cmd, bash, git-bash, wsl, zsh, fish, nu, or an absolute executable path"},
                    "cwd": {"type": "string"},
                    "timeout_s": {"type": "integer"},
                },
                "required": ["command"],
            },
            is_destructive=True,
            max_result_size_chars=50_000,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        command = str(tool_input.get("command") or "").strip().replace("\n", " ")
        shell = str(tool_input.get("shell") or "auto")
        preview = command if len(command) <= 120 else command[:117] + "..."
        return maybe_ask_for_gated_tool(
            context,
            "Terminal",
            f"Run with {shell}: {preview or '(empty)'}",
            "Allow Terminal for the rest of this conversation",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        output = run_terminal_command(tool_input, context)
        return ToolResult(name="Terminal", output=output, is_error=output["exit_code"] != 0)
