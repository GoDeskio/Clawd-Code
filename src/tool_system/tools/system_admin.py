from __future__ import annotations

import json
import importlib.util
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..audit import audit_path, read_actions
from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


def system_admin_capabilities() -> dict[str, Any]:
    return {
        "ready": importlib.util.find_spec("psutil") is not None,
        "administrator": SystemAdminTool._is_admin(),
        "audit_path": str(audit_path()),
        "git": shutil.which("git"),
        "package_managers": [name for name in ("winget", "choco", "npm", "apt", "dnf", "brew") if shutil.which(name)],
    }


def _psutil() -> Any:
    try:
        import psutil
    except ImportError as exc:
        raise ToolExecutionError("System administrator dependencies are missing; restart Jonathan Ai to auto-install them") from exc
    return psutil


def _snapshot(*, process_limit: int = 20, connections: bool = False) -> dict[str, Any]:
    psutil = _psutil()
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for partition in psutil.disk_partitions(all=False):
        if partition.mountpoint in seen:
            continue
        seen.add(partition.mountpoint)
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append({"device": partition.device, "mountpoint": partition.mountpoint, "filesystem": partition.fstype,
                      "total": usage.total, "used": usage.used, "free": usage.free, "percent": usage.percent})
    processes: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "username", "status", "memory_info", "cpu_percent", "create_time"]):
        try:
            info = process.info
            processes.append({"pid": info["pid"], "name": info.get("name"), "username": info.get("username"),
                              "status": info.get("status"), "cpu_percent": info.get("cpu_percent") or 0,
                              "memory_rss": getattr(info.get("memory_info"), "rss", 0),
                              "started_at": datetime.fromtimestamp(info.get("create_time") or 0, timezone.utc).isoformat()})
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    processes.sort(key=lambda row: (row["memory_rss"], row["cpu_percent"]), reverse=True)
    network = psutil.net_io_counters()
    result: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": {"hostname": socket.gethostname(), "platform": platform.platform(), "architecture": platform.machine(),
                 "python": sys.version.split()[0], "boot_time": datetime.fromtimestamp(psutil.boot_time(), timezone.utc).isoformat()},
        "cpu": {"logical": psutil.cpu_count(), "physical": psutil.cpu_count(logical=False), "percent": psutil.cpu_percent(interval=0.15),
                "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None},
        "memory": {"total": memory.total, "available": memory.available, "used": memory.used, "percent": memory.percent,
                   "swap_total": swap.total, "swap_used": swap.used, "swap_percent": swap.percent},
        "disks": disks,
        "network": {"bytes_sent": network.bytes_sent, "bytes_received": network.bytes_recv,
                    "packets_sent": network.packets_sent, "packets_received": network.packets_recv,
                    "interfaces": sorted(psutil.net_if_addrs().keys())},
        "top_processes": processes[:max(1, min(200, process_limit))],
    }
    if connections:
        try:
            result["connections"] = [{"fd": row.fd, "family": str(row.family), "type": str(row.type),
                                      "local": str(row.laddr), "remote": str(row.raddr), "status": row.status, "pid": row.pid}
                                     for row in psutil.net_connections(kind="inet")[:500]]
        except (PermissionError, psutil.AccessDenied):
            result["connections_error"] = "administrator privileges are required to enumerate all connections"
    return result


def _evaluation(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cpu = float(snapshot["cpu"].get("percent") or 0)
    memory = float(snapshot["memory"].get("percent") or 0)
    if cpu >= 90:
        findings.append({"severity": "critical", "area": "cpu", "message": f"CPU utilization is {cpu:.1f}%"})
    elif cpu >= 75:
        findings.append({"severity": "warning", "area": "cpu", "message": f"CPU utilization is {cpu:.1f}%"})
    if memory >= 90:
        findings.append({"severity": "critical", "area": "memory", "message": f"Memory utilization is {memory:.1f}%"})
    elif memory >= 80:
        findings.append({"severity": "warning", "area": "memory", "message": f"Memory utilization is {memory:.1f}%"})
    for disk in snapshot.get("disks") or []:
        percent = float(disk.get("percent") or 0)
        if percent >= 90:
            findings.append({"severity": "critical", "area": "disk", "message": f"{disk['mountpoint']} is {percent:.1f}% full"})
        elif percent >= 80:
            findings.append({"severity": "warning", "area": "disk", "message": f"{disk['mountpoint']} is {percent:.1f}% full"})
    if not findings:
        findings.append({"severity": "ok", "area": "system", "message": "No CPU, memory, or disk threshold violations detected"})
    return findings


def _services() -> list[dict[str, Any]]:
    psutil = _psutil()
    if os.name == "nt" and hasattr(psutil, "win_service_iter"):
        rows = []
        for service in psutil.win_service_iter():
            try:
                info = service.as_dict()
                rows.append({key: info.get(key) for key in ("name", "display_name", "status", "start_type", "username", "binpath")})
            except (OSError, psutil.Error):
                continue
        return rows
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return []
    completed = subprocess.run([systemctl, "list-units", "--type=service", "--all", "--no-legend", "--no-pager"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    return [{"raw": line} for line in completed.stdout.splitlines() if line.strip()]


class SystemAdminTool:
    READ_ONLY = {"capabilities", "snapshot", "evaluate", "processes", "services", "network", "audit"}

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="SystemAdmin",
            description=(
                "Administer the computer with structured inventory, health/resource monitoring, evaluation, process and service control, "
                "package installation, persistent audit history, and downloadable reports. Machine-changing actions require approval."
            ),
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["capabilities", "snapshot", "evaluate", "monitor", "processes", "process", "services", "service", "network", "install_package", "audit", "report"]},
                    "pid": {"type": "integer", "minimum": 1}, "operation": {"type": "string", "enum": ["terminate", "kill", "start", "stop", "restart"]},
                    "service": {"type": "string"}, "package": {"type": "string"},
                    "manager": {"type": "string", "enum": ["auto", "winget", "choco", "pip", "npm", "apt", "dnf", "brew"]},
                    "duration": {"type": "number", "minimum": 0.25, "maximum": 300}, "interval": {"type": "number", "minimum": 0.25, "maximum": 60},
                    "process_limit": {"type": "integer", "minimum": 1, "maximum": 200}, "include_connections": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000}, "tool": {"type": "string"},
                    "session_id": {"type": "string"}, "output": {"type": "string"}, "format": {"type": "string", "enum": ["json", "markdown"]},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 3600}
                },
                "required": ["action"]
            },
            is_destructive=True, max_result_size_chars=100_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "")
        if action in self.READ_ONLY:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "SystemAdmin", f"Run system administrator action '{action}'",
                                        "Allow SystemAdmin changes for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "capabilities":
            return ToolResult(name="SystemAdmin", output={
                "platform": platform.platform(), "administrator": self._is_admin(),
                "package_managers": [name for name in ("winget", "choco", "npm", "apt", "dnf", "brew") if shutil.which(name)],
                "features": ["health snapshots", "resource evaluation", "process control", "service control", "network inventory", "package installation", "persistent audit log", "downloadable reports"],
                "audit_path": str(audit_path()),
            })
        if action in {"snapshot", "evaluate", "network", "processes"}:
            snapshot = _snapshot(process_limit=int(tool_input.get("process_limit") or 20),
                                 connections=bool(tool_input.get("include_connections") or action == "network"))
            if action == "evaluate":
                snapshot["evaluation"] = _evaluation(snapshot)
            if action == "processes":
                return ToolResult(name="SystemAdmin", output={"captured_at": snapshot["captured_at"], "processes": snapshot["top_processes"]})
            if action == "network":
                return ToolResult(name="SystemAdmin", output={key: snapshot[key] for key in ("captured_at", "host", "network", "connections") if key in snapshot})
            return ToolResult(name="SystemAdmin", output=snapshot)
        if action == "services":
            return ToolResult(name="SystemAdmin", output={"services": _services()})
        if action == "process":
            return self._process(tool_input)
        if action == "service":
            return self._service(tool_input)
        if action == "install_package":
            return self._install_package(tool_input)
        if action == "monitor":
            return self._monitor(tool_input, context)
        if action == "audit":
            return ToolResult(name="SystemAdmin", output={"path": str(audit_path()), "actions": read_actions(
                int(tool_input.get("limit") or 200), tool=str(tool_input.get("tool") or ""), session_id=str(tool_input.get("session_id") or ""))})
        if action == "report":
            return self._report(tool_input, context)
        raise ToolInputError(f"unsupported administrator action: {action}")

    @staticmethod
    def _is_admin() -> bool:
        if os.name == "nt":
            try:
                import ctypes
                return bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                return False
        return hasattr(os, "geteuid") and os.geteuid() == 0

    @staticmethod
    def _process(tool_input: dict[str, Any]) -> ToolResult:
        psutil = _psutil()
        pid = int(tool_input.get("pid") or 0)
        operation = str(tool_input.get("operation") or "terminate")
        if not pid:
            raise ToolInputError("pid is required for process control")
        if pid in {os.getpid(), os.getppid()}:
            raise ToolInputError("refusing to stop Jonathan Ai or its desktop host")
        try:
            process = psutil.Process(pid)
            before = {"pid": pid, "name": process.name(), "status": process.status()}
            process.kill() if operation == "kill" else process.terminate()
            try:
                process.wait(timeout=10)
            except psutil.TimeoutExpired:
                pass
            return ToolResult(name="SystemAdmin", output={"operation": operation, "process": before, "running": process.is_running()})
        except psutil.NoSuchProcess:
            raise ToolInputError(f"process {pid} does not exist")

    @staticmethod
    def _service(tool_input: dict[str, Any]) -> ToolResult:
        name = str(tool_input.get("service") or "").strip()
        operation = str(tool_input.get("operation") or "").strip()
        if not name or operation not in {"start", "stop", "restart"}:
            raise ToolInputError("service and operation=start|stop|restart are required")
        if os.name == "nt":
            commands = {"start": [["sc.exe", "start", name]], "stop": [["sc.exe", "stop", name]],
                        "restart": [["sc.exe", "stop", name], ["sc.exe", "start", name]]}[operation]
        else:
            systemctl = shutil.which("systemctl")
            if not systemctl:
                raise ToolExecutionError("systemctl is unavailable")
            commands = [[systemctl, operation, name]]
        outputs = []
        for command in commands:
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            outputs.append({"command": command, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
            if completed.returncode != 0 and not (operation == "restart" and command == commands[0]):
                return ToolResult(name="SystemAdmin", output={"service": name, "operation": operation, "steps": outputs}, is_error=True)
        return ToolResult(name="SystemAdmin", output={"service": name, "operation": operation, "steps": outputs})

    @staticmethod
    def _install_package(tool_input: dict[str, Any]) -> ToolResult:
        package = str(tool_input.get("package") or "").strip()
        if not package or any(char in package for char in ";&|`\r\n"):
            raise ToolInputError("package must be one package identifier without shell operators")
        requested = str(tool_input.get("manager") or "auto")
        managers = [requested] if requested != "auto" else (["winget", "choco", "pip", "npm"] if os.name == "nt" else ["apt", "dnf", "brew", "pip", "npm"])
        manager = next((item for item in managers if item == "pip" or shutil.which(item)), None)
        if not manager:
            raise ToolExecutionError("no supported package manager was found")
        executable = sys.executable if manager == "pip" else str(shutil.which(manager))
        commands = {
            "winget": [executable, "install", "--id", package, "--exact", "--accept-package-agreements", "--accept-source-agreements"],
            "choco": [executable, "install", package, "-y"], "pip": [executable, "-m", "pip", "install", package],
            "npm": [executable, "install", "--global", package], "apt": [executable, "install", "-y", package],
            "dnf": [executable, "install", "-y", package], "brew": [executable, "install", package],
        }
        completed = subprocess.run(commands[manager], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=int(tool_input.get("timeout") or 1800))
        return ToolResult(name="SystemAdmin", output={"manager": manager, "package": package, "exit_code": completed.returncode,
            "stdout": completed.stdout[-8000:], "stderr": completed.stderr[-8000:]}, is_error=completed.returncode != 0)

    @staticmethod
    def _monitor(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        duration = float(tool_input.get("duration") or 10)
        interval = float(tool_input.get("interval") or 2)
        deadline = time.monotonic() + duration
        samples = []
        while True:
            snapshot = _snapshot(process_limit=int(tool_input.get("process_limit") or 10))
            samples.append({"captured_at": snapshot["captured_at"], "cpu": snapshot["cpu"], "memory": snapshot["memory"], "disks": snapshot["disks"], "evaluation": _evaluation(snapshot)})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
        output = context.ensure_allowed_path(str(tool_input.get("output") or "admin/system-monitor.json"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"duration": duration, "interval": interval, "samples": samples}, indent=2, ensure_ascii=False), encoding="utf-8")
        artifacts = [context.artifact_publisher(output, output.name)] if context.artifact_publisher else []
        return ToolResult(name="SystemAdmin", output={"path": str(output), "sample_count": len(samples), "samples": samples,
            "artifact": artifacts[0] if artifacts else None, "artifacts": artifacts})

    @staticmethod
    def _report(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        snapshot = _snapshot(process_limit=int(tool_input.get("process_limit") or 20), connections=bool(tool_input.get("include_connections")))
        snapshot["evaluation"] = _evaluation(snapshot)
        fmt = str(tool_input.get("format") or "markdown")
        default = "admin/system-report.json" if fmt == "json" else "admin/system-report.md"
        output = context.ensure_allowed_path(str(tool_input.get("output") or default))
        output.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            text = json.dumps(snapshot, indent=2, ensure_ascii=False)
        else:
            text = "\n".join([
                "# Jonathan Ai System Report", "", f"Generated: {snapshot['captured_at']}",
                f"Host: {snapshot['host']['hostname']} · {snapshot['host']['platform']}",
                f"CPU: {snapshot['cpu']['percent']}% · Memory: {snapshot['memory']['percent']}%", "",
                "## Evaluation", *[f"- **{item['severity']}** {item['area']}: {item['message']}" for item in snapshot["evaluation"]], "",
                "## Disks", *[f"- {disk['mountpoint']}: {disk['percent']}% used ({disk['free']} bytes free)" for disk in snapshot["disks"]], "",
                "## Top processes", *[f"- {row['pid']} · {row['name']} · {row['memory_rss']} bytes" for row in snapshot["top_processes"]],
            ]) + "\n"
        output.write_text(text, encoding="utf-8")
        artifacts = [context.artifact_publisher(output, output.name)] if context.artifact_publisher else []
        return ToolResult(name="SystemAdmin", output={"path": str(output), "evaluation": snapshot["evaluation"],
            "artifact": artifacts[0] if artifacts else None, "artifacts": artifacts})
