from __future__ import annotations

import os
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.device_control import discover_browsers, discover_device_controls, resolve_application

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class DeviceControlTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="DeviceControl",
            description=(
                "Discover and use applications, browsers, files, URLs, and executables installed on the computer. "
                "Launches inherit the signed-in user's environment. Full-device mode is required outside the workspace; OS ACL and UAC rules still apply."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["inventory", "launch", "launch_elevated", "open", "open_url", "reveal", "screenshot", "click", "type_text", "press", "hotkey"]},
                    "application": {"type": "string"},
                    "arguments": {"type": "array", "items": {"type": "string"}},
                    "target": {"type": "string"},
                    "url": {"type": "string"},
                    "browser": {"type": "string"},
                    "cwd": {"type": "string"},
                    "wait": {"type": "boolean"},
                    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 3600},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                    "x": {"type": "integer", "minimum": 0},
                    "y": {"type": "integer", "minimum": 0},
                    "button": {"type": "string", "enum": ["left", "middle", "right"]},
                    "text": {"type": "string"},
                    "keys": {"type": "array", "items": {"type": "string"}},
                    "interval": {"type": "number", "minimum": 0, "maximum": 5},
                    "output": {"type": "string"},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=150_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "")
        subject = tool_input.get("application") or tool_input.get("target") or tool_input.get("url") or "installed software"
        return maybe_ask_for_gated_tool(
            context,
            "DeviceControl",
            f"Use device action '{action}' on {subject}",
            "Allow DeviceControl for the rest of this conversation",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input.get("action") or "")
        if action == "inventory":
            return ToolResult(name="DeviceControl", output=discover_device_controls(limit=int(tool_input.get("limit") or 2000)))
        if action == "launch":
            return self._launch(tool_input, context)
        if action == "launch_elevated":
            return self._launch_elevated(tool_input, context)
        if action == "open":
            return self._open(tool_input, context)
        if action == "open_url":
            return self._open_url(tool_input, context)
        if action == "reveal":
            return self._reveal(tool_input, context)
        if action == "screenshot":
            return self._screenshot(tool_input, context)
        if action in {"click", "type_text", "press", "hotkey"}:
            return self._gui(action, tool_input)
        raise ToolInputError(f"unsupported device action: {action}")

    @staticmethod
    def _launch(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            executable = resolve_application(str(tool_input.get("application") or ""))
        except ValueError as exc:
            raise ToolInputError(str(exc)) from exc
        context.ensure_allowed_path(executable)
        arguments = tool_input.get("arguments") or []
        if not isinstance(arguments, list) or not all(isinstance(item, str) and "\x00" not in item for item in arguments):
            raise ToolInputError("arguments must be an array of strings")
        raw_cwd = tool_input.get("cwd")
        cwd = context.ensure_allowed_path(str(raw_cwd)) if raw_cwd else executable.parent
        if not cwd.is_dir():
            raise ToolInputError(f"cwd is not a directory: {cwd}")
        command = [str(executable), *arguments]
        try:
            if tool_input.get("wait"):
                completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=int(tool_input.get("timeout_s") or 300))
                return ToolResult(name="DeviceControl", output={"application": str(executable), "arguments": arguments, "exit_code": completed.returncode, "stdout": completed.stdout[-20_000:], "stderr": completed.stderr[-20_000:]}, is_error=completed.returncode != 0)
            process = subprocess.Popen(command, cwd=str(cwd))
            return ToolResult(name="DeviceControl", output={"application": str(executable), "arguments": arguments, "pid": process.pid, "launched": True})
        except (OSError, subprocess.SubprocessError) as exc:
            raise ToolExecutionError(str(exc)) from exc

    @staticmethod
    def _launch_elevated(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if os.name != "nt":
            raise ToolInputError("launch_elevated is available on Windows; use sudo through Terminal on Unix")
        try:
            executable = context.ensure_allowed_path(resolve_application(str(tool_input.get("application") or "")))
        except ValueError as exc:
            raise ToolInputError(str(exc)) from exc
        arguments = tool_input.get("arguments") or []
        if not isinstance(arguments, list) or not all(isinstance(item, str) and "\x00" not in item for item in arguments):
            raise ToolInputError("arguments must be an array of strings")
        raw_cwd = tool_input.get("cwd")
        cwd = context.ensure_allowed_path(str(raw_cwd)) if raw_cwd else executable.parent
        import ctypes

        result = int(ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(executable),
            subprocess.list2cmdline(arguments) if arguments else None,
            str(cwd),
            1,
        ))
        if result <= 32:
            raise ToolExecutionError(f"Windows elevation was cancelled or failed (ShellExecute code {result})")
        return ToolResult(name="DeviceControl", output={"application": str(executable), "arguments": arguments, "elevation_requested": True, "uac_prompted": True})

    @staticmethod
    def _open(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        target = context.ensure_allowed_path(str(tool_input.get("target") or ""))
        if not target.exists():
            raise ToolInputError(f"target does not exist: {target}")
        try:
            if os.name == "nt":
                os.startfile(str(target))
            elif __import__("sys").platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return ToolResult(name="DeviceControl", output={"target": str(target), "opened": True})

    @staticmethod
    def _open_url(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        url = str(tool_input.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ToolInputError("url must be an absolute http:// or https:// URL")
        requested = str(tool_input.get("browser") or "").strip()
        if requested:
            wanted = requested.lower()
            match = next((item for item in discover_browsers() if wanted in {item["name"].lower(), Path(item["path"]).stem.lower(), Path(item["path"]).name.lower()}), None)
            try:
                executable = context.ensure_allowed_path(match["path"] if match else resolve_application(requested))
            except ValueError as exc:
                raise ToolInputError(f"installed browser was not found: {requested}") from exc
            process = subprocess.Popen([str(executable), url])
            return ToolResult(name="DeviceControl", output={"url": url, "browser": match["name"] if match else executable.stem, "pid": process.pid, "opened": True})
        opened = bool(webbrowser.open(url, new=2))
        return ToolResult(name="DeviceControl", output={"url": url, "browser": "system default", "opened": opened}, is_error=not opened)

    @staticmethod
    def _reveal(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        target = context.ensure_allowed_path(str(tool_input.get("target") or ""))
        if not target.exists():
            raise ToolInputError(f"target does not exist: {target}")
        if os.name == "nt":
            command = ["explorer.exe", "/select,", str(target)] if target.is_file() else ["explorer.exe", str(target)]
        elif __import__("sys").platform == "darwin":
            command = ["open", "-R", str(target)]
        else:
            command = ["xdg-open", str(target.parent if target.is_file() else target)]
        process = subprocess.Popen(command)
        return ToolResult(name="DeviceControl", output={"target": str(target), "pid": process.pid, "revealed": True})

    @staticmethod
    def _pyautogui():
        try:
            import pyautogui
        except ImportError as exc:
            raise ToolExecutionError("Desktop automation dependency is missing; restart Jonathan Ai to auto-install it") from exc
        # Keep the library's upper-left emergency stop enabled.
        pyautogui.FAILSAFE = True
        return pyautogui

    @classmethod
    def _screenshot(cls, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        default = f"device/screenshots/desktop-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        output = context.ensure_allowed_path(str(tool_input.get("output") or default))
        if output.suffix.lower() != ".png":
            raise ToolInputError("desktop screenshots must use a .png output path")
        output.parent.mkdir(parents=True, exist_ok=True)
        image = cls._pyautogui().screenshot()
        image.save(output, format="PNG")
        artifacts = [context.artifact_publisher(output, output.name)] if context.artifact_publisher else []
        return ToolResult(name="DeviceControl", output={"action": "screenshot", "path": str(output), "width": image.width, "height": image.height, "artifact": artifacts[0] if artifacts else None, "artifacts": artifacts})

    @classmethod
    def _gui(cls, action: str, tool_input: dict[str, Any]) -> ToolResult:
        gui = cls._pyautogui()
        interval = float(tool_input.get("interval") or 0.02)
        if action == "click":
            if tool_input.get("x") is None or tool_input.get("y") is None:
                raise ToolInputError("x and y are required for click")
            gui.click(x=int(tool_input["x"]), y=int(tool_input["y"]), button=str(tool_input.get("button") or "left"))
            return ToolResult(name="DeviceControl", output={"action": action, "x": int(tool_input["x"]), "y": int(tool_input["y"]), "button": str(tool_input.get("button") or "left")})
        if action == "type_text":
            text = str(tool_input.get("text") or "")
            if not text:
                raise ToolInputError("text is required for type_text")
            gui.write(text, interval=interval)
            return ToolResult(name="DeviceControl", output={"action": action, "characters": len(text)})
        keys = tool_input.get("keys") or []
        if not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key.strip() for key in keys):
            raise ToolInputError("keys must be a non-empty array of key names")
        if action == "press":
            for key in keys:
                gui.press(key, interval=interval)
        else:
            gui.hotkey(*keys, interval=interval)
        return ToolResult(name="DeviceControl", output={"action": action, "keys": keys})
