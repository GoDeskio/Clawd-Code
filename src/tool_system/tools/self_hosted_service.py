"""Approval-gated lifecycle management for user-registered self-hosted services."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.providers.local_endpoints import assert_local_or_lan_url

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


_READ_ACTIONS = {"capabilities", "list", "inspect", "status", "logs"}
_DRIVERS = {"docker_compose", "windows_service", "systemd"}
_LOCK = threading.RLock()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _store_path() -> Path:
    override = os.environ.get("JONATHAN_SERVICE_STORE", "").strip()
    return Path(override).expanduser().resolve() if override else Path.home() / ".clawd" / "self-hosted" / "services.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"version": 1, "services": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolExecutionError("self-hosted service registry is unreadable") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("services"), list):
        raise ToolExecutionError("self-hosted service registry is invalid")
    return payload


def _save(payload: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise ToolExecutionError("could not persist the self-hosted service registry") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _clean(value: Any, name: str, *, required: bool = True, limit: int = 2000) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ToolInputError(f"{name} is required")
    if len(text) > limit or any(char in text for char in "\r\n\0"):
        raise ToolInputError(f"{name} is invalid")
    return text


def _service(payload: dict[str, Any], service_id: str, *, include_archived: bool = False) -> dict[str, Any]:
    for item in payload["services"]:
        if item.get("id") == service_id and (include_archived or not item.get("archived")):
            return item
    raise ToolInputError(f"self-hosted service not found: {service_id}")


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolExecutionError(f"service command failed to start: {command[0]}") from exc
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-40_000:],
        "stderr": completed.stderr[-20_000:],
    }


def _run_sequence(commands: list[list[str]], *, cwd: Path | None = None, timeout: int = 120) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for command in commands:
        step = _run(command, cwd=cwd, timeout=timeout)
        steps.append(step)
        if step["exit_code"] != 0:
            break
    return steps


def _compose(service: dict[str, Any], context: ToolContext) -> tuple[list[str], Path]:
    project = context.ensure_allowed_path(_clean(service.get("project_dir"), "project_dir"))
    if not project.is_dir():
        raise ToolInputError("registered compose project directory does not exist")
    compose_value = str(service.get("compose_file") or "compose.yaml")
    compose = context.ensure_allowed_path(compose_value if Path(compose_value).is_absolute() else project / compose_value)
    try:
        compose.relative_to(project)
    except ValueError as exc:
        raise ToolInputError("compose_file must stay inside the registered project directory") from exc
    if not compose.is_file():
        raise ToolInputError(f"compose file does not exist: {compose}")
    requested = str(service.get("engine") or "auto")
    candidates = [requested] if requested != "auto" else ["docker", "podman"]
    executable = next((shutil.which(name) for name in candidates if shutil.which(name)), None)
    if not executable:
        raise ToolExecutionError("Docker or Podman Compose is not installed")
    return [str(executable), "compose", "-f", str(compose)], project


def _health(url: str, timeout: int) -> dict[str, Any]:
    endpoint = assert_local_or_lan_url(url)
    try:
        with urlopen(Request(endpoint, headers={"User-Agent": "JonathanAi/0.4.9"}), timeout=min(timeout, 30)) as response:
            return {"url": endpoint, "reachable": True, "status": int(getattr(response, "status", 200) or 200)}
    except HTTPError as exc:
        return {"url": endpoint, "reachable": True, "status": int(exc.code)}
    except (URLError, OSError) as exc:
        return {"url": endpoint, "reachable": False, "error": str(exc)}


class SelfHostedServiceTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="SelfHostedService",
            description=(
                "Register and operate approved Docker/Podman Compose, Windows-service, or systemd workloads with "
                "status, local/LAN health checks, bounded logs, backups, lifecycle control, and pull/update."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": [
                        "capabilities", "list", "register", "inspect", "status", "logs", "backup",
                        "start", "stop", "restart", "update", "remove",
                    ]},
                    "service_id": {"type": "string"}, "name": {"type": "string"},
                    "driver": {"type": "string", "enum": sorted(_DRIVERS)},
                    "engine": {"type": "string", "enum": ["auto", "docker", "podman"]},
                    "project_dir": {"type": "string"}, "compose_file": {"type": "string"},
                    "service_name": {"type": "string"}, "health_url": {"type": "string"},
                    "homepage": {"type": "string"}, "notes": {"type": "string"},
                    "backup_paths": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                    "output": {"type": "string"}, "tail": {"type": "integer", "minimum": 1, "maximum": 5000},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 3600},
                    "include_archived": {"type": "boolean"},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=120_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "")
        if action in _READ_ACTIONS:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(
            context,
            "SelfHostedService",
            f"Run approved self-hosted service action: {action}",
            "Allow self-hosted service changes for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "capabilities":
            return ToolResult(name="SelfHostedService", output={
                "docker": shutil.which("docker"), "podman": shutil.which("podman"),
                "systemctl": shutil.which("systemctl"), "windows_services": os.name == "nt",
                "drivers": sorted(_DRIVERS), "registry": str(_store_path()),
                "safety": "registered manifests, fixed arguments, no shell, approval before mutations",
            })
        payload = _load()
        if action == "list":
            include_archived = bool(tool_input.get("include_archived"))
            services = [item for item in payload["services"] if include_archived or not item.get("archived")]
            return ToolResult(name="SelfHostedService", output={"services": services, "count": len(services)})
        if action == "register":
            service = self._register(tool_input, context)
            with _LOCK:
                payload = _load()
                payload["services"].append(service)
                _save(payload)
            return ToolResult(name="SelfHostedService", output={"registered": True, "service": service})

        service_id = _clean(tool_input.get("service_id"), "service_id", limit=80)
        service = _service(payload, service_id, include_archived=action == "remove")
        if action == "inspect":
            return ToolResult(name="SelfHostedService", output=service)
        if action == "remove":
            with _LOCK:
                payload = _load()
                service = _service(payload, service_id, include_archived=True)
                service.update({"archived": True, "updated_at": _stamp()})
                _save(payload)
            return ToolResult(name="SelfHostedService", output={"archived": True, "recoverable": True, "service": service})
        if action == "backup":
            output = self._backup(service, tool_input, context)
            with _LOCK:
                payload = _load()
                current = _service(payload, service_id)
                current["last_backup"] = {key: output[key] for key in ("path", "files", "bytes")}
                current["last_backup"]["created_at"] = _stamp()
                current["updated_at"] = _stamp()
                _save(payload)
            return ToolResult(name="SelfHostedService", output=output)
        if action in {"status", "logs", "start", "stop", "restart", "update"}:
            if action == "update" and service.get("backup_paths") and not service.get("last_backup"):
                raise ToolInputError("create a service backup before its first managed update")
            output = self._operate(service, action, tool_input, context)
            if action not in _READ_ACTIONS:
                with _LOCK:
                    payload = _load()
                    _service(payload, service_id)["updated_at"] = _stamp()
                    _save(payload)
            return ToolResult(name="SelfHostedService", output=output, is_error=bool(output.get("is_error")))
        raise ToolInputError(f"unsupported self-hosted service action: {action}")

    @staticmethod
    def _register(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        driver = str(tool_input.get("driver") or "")
        if driver not in _DRIVERS:
            raise ToolInputError("driver is required")
        service_id = f"service_{uuid.uuid4().hex[:12]}"
        health_url = _clean(tool_input.get("health_url"), "health_url", required=False)
        if health_url:
            health_url = assert_local_or_lan_url(health_url)
        project_dir = _clean(tool_input.get("project_dir"), "project_dir", required=False)
        service_name = _clean(tool_input.get("service_name"), "service_name", required=False)
        compose_file = _clean(tool_input.get("compose_file"), "compose_file", required=False) or "compose.yaml"
        if driver == "docker_compose":
            project = context.ensure_allowed_path(project_dir)
            if not project.is_dir():
                raise ToolInputError("project_dir must be an existing allowed directory")
            compose = context.ensure_allowed_path(compose_file if Path(compose_file).is_absolute() else project / compose_file)
            try:
                compose.relative_to(project)
            except ValueError as exc:
                raise ToolInputError("compose_file must stay inside project_dir") from exc
            if not compose.is_file():
                raise ToolInputError("compose_file must exist before registration")
            project_dir, compose_file = str(project), str(compose.relative_to(project))
        elif not service_name:
            raise ToolInputError("service_name is required for an operating-system service")
        backup_paths = [_clean(value, "backup path") for value in tool_input.get("backup_paths") or []]
        return {
            "id": service_id, "name": _clean(tool_input.get("name"), "name", limit=200), "driver": driver,
            "engine": str(tool_input.get("engine") or "auto"), "project_dir": project_dir or None,
            "compose_file": compose_file if driver == "docker_compose" else None,
            "service_name": service_name or None, "health_url": health_url or None,
            "homepage": _clean(tool_input.get("homepage"), "homepage", required=False) or None,
            "notes": _clean(tool_input.get("notes"), "notes", required=False, limit=4000) or None,
            "backup_paths": backup_paths, "archived": False, "created_at": _stamp(), "updated_at": _stamp(),
        }

    @staticmethod
    def _operate(service: dict[str, Any], action: str, tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        timeout = int(tool_input.get("timeout") or 120)
        driver = service["driver"]
        steps: list[dict[str, Any]] = []
        if driver == "docker_compose":
            prefix, cwd = _compose(service, context)
            commands = {
                "status": [prefix + ["ps", "--format", "json"]],
                "logs": [prefix + ["logs", "--no-color", "--tail", str(int(tool_input.get("tail") or 200))]],
                "start": [prefix + ["up", "-d"]], "stop": [prefix + ["down"]],
                "restart": [prefix + ["restart"]],
                "update": [prefix + ["pull"], prefix + ["up", "-d"]],
            }[action]
            steps = _run_sequence(commands, cwd=cwd, timeout=timeout)
        elif driver == "windows_service":
            if os.name != "nt":
                raise ToolExecutionError("Windows service control is unavailable on this platform")
            name = str(service["service_name"])
            if action == "logs" or action == "update":
                raise ToolInputError(f"{action} is not portable for a Windows service; use its documented updater or event source")
            commands = {
                "status": [["sc.exe", "query", name]], "start": [["sc.exe", "start", name]],
                "stop": [["sc.exe", "stop", name]],
                "restart": [["sc.exe", "stop", name], ["sc.exe", "start", name]],
            }[action]
            steps = _run_sequence(commands, timeout=timeout)
        else:
            systemctl = shutil.which("systemctl")
            if not systemctl:
                raise ToolExecutionError("systemctl is unavailable")
            name = str(service["service_name"])
            if action == "update":
                raise ToolInputError("systemd update requires a service-specific package/container workflow")
            commands = {
                "status": [[systemctl, "show", name, "--no-pager"]],
                "logs": [[str(shutil.which("journalctl") or "journalctl"), "-u", name, "--no-pager", "-n", str(int(tool_input.get("tail") or 200))]],
                "start": [[systemctl, "start", name]], "stop": [[systemctl, "stop", name]],
                "restart": [[systemctl, "restart", name]],
            }[action]
            steps = _run_sequence(commands, timeout=timeout)
        health = _health(str(service["health_url"]), timeout) if service.get("health_url") and action != "logs" else None
        return {
            "service_id": service["id"], "name": service["name"], "driver": driver, "action": action,
            "steps": steps, "health": health,
            "is_error": any(step["exit_code"] != 0 for step in steps),
        }

    @staticmethod
    def _backup(service: dict[str, Any], tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        values = list(service.get("backup_paths") or [])
        if not values:
            raise ToolInputError("register at least one backup_path before backing up this service")
        project = Path(str(service.get("project_dir") or context.workspace_root))
        roots: list[Path] = []
        for value in values:
            path = Path(value)
            resolved = context.ensure_allowed_path(path if path.is_absolute() else project / path)
            if not resolved.exists():
                raise ToolInputError(f"backup path does not exist: {resolved}")
            roots.append(resolved)
        output = context.ensure_allowed_path(str(tool_input.get("output") or f"backups/{service['id']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"))
        if output.suffix.lower() != ".zip":
            raise ToolInputError("backup output must be a .zip file")
        output.parent.mkdir(parents=True, exist_ok=True)
        file_count = 0
        total_bytes = 0
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for root in roots:
                paths = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
                for path in paths:
                    if path.is_symlink():
                        continue
                    size = path.stat().st_size
                    file_count += 1
                    total_bytes += size
                    if file_count > 10_000 or total_bytes > 10 * 1024 ** 3:
                        raise ToolInputError("backup exceeds the 10,000-file or 10 GB safety limit")
                    archive.write(path, arcname=f"{root.name}/{path.relative_to(root) if root.is_dir() else path.name}")
        artifacts = [context.artifact_publisher(output, output.name)] if context.artifact_publisher else []
        return {"service_id": service["id"], "path": str(output), "files": file_count, "bytes": total_bytes, "artifacts": artifacts}
