from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


def _git() -> str:
    executable = shutil.which("git")
    if not executable:
        raise ToolExecutionError("Git is not installed or was not found on PATH")
    return executable


def _safe_remote(value: str) -> str:
    return re.sub(r"(https?://)[^/@:]+:[^/@]+@", r"\1[redacted]@", value)


def _run(args: list[str], cwd: Path, timeout: int = 300) -> dict[str, Any]:
    completed = subprocess.run([_git(), *args], cwd=str(cwd), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
    return {"args": ["git", *args], "exit_code": completed.returncode,
            "stdout": _safe_remote(completed.stdout), "stderr": _safe_remote(completed.stderr)}


class RepositoryTool:
    READ_ONLY = {"status", "log", "diff", "remotes"}

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Repository",
            description=(
                "Inspect, clone, fetch, pull, and push Git repositories on GitHub, GitLab, or any Git host. "
                "It never merges branches and protects main/master pushes unless explicitly authorized."
            ),
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["status", "log", "diff", "remotes", "clone", "fetch", "pull", "push"]},
                    "path": {"type": "string"}, "url": {"type": "string"}, "destination": {"type": "string"},
                    "remote": {"type": "string"}, "branch": {"type": "string"}, "base": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "rebase": {"type": "boolean"},
                    "set_upstream": {"type": "boolean"}, "allow_protected_branch": {"type": "boolean"},
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
        return maybe_ask_for_gated_tool(context, "Repository", f"Run git {action} for {tool_input.get('path') or tool_input.get('destination') or context.cwd}",
                                        "Allow Repository changes for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        timeout = int(tool_input.get("timeout") or 300)
        if action == "clone":
            url = str(tool_input.get("url") or "").strip()
            destination = str(tool_input.get("destination") or "").strip()
            if not url or not destination or any(char in url for char in "\r\n"):
                raise ToolInputError("url and destination are required for clone")
            target = context.ensure_allowed_path(destination)
            if target.exists() and any(target.iterdir()):
                raise ToolInputError(f"clone destination is not empty: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            result = _run(["clone", url, str(target)], target.parent, timeout)
            result["path"] = str(target)
            result["url"] = _safe_remote(url)
            return ToolResult(name="Repository", output=result, is_error=result["exit_code"] != 0)
        path = context.ensure_allowed_path(str(tool_input.get("path") or context.cwd))
        if not (path / ".git").exists():
            probe = _run(["rev-parse", "--show-toplevel"], path, timeout)
            if probe["exit_code"] != 0:
                raise ToolInputError(f"not a Git repository: {path}")
        remote = str(tool_input.get("remote") or "origin")
        if action == "status":
            branch = _run(["branch", "--show-current"], path, timeout)
            status = _run(["status", "--short", "--branch"], path, timeout)
            return ToolResult(name="Repository", output={"path": str(path), "branch": branch["stdout"].strip(), "status": status})
        if action == "log":
            result = _run(["log", f"-{int(tool_input.get('limit') or 20)}", "--date=iso", "--pretty=format:%h%x09%ad%x09%an%x09%s"], path, timeout)
        elif action == "diff":
            args = ["diff", "--stat"]
            if tool_input.get("base"):
                args.append(str(tool_input["base"]))
            result = _run(args, path, timeout)
        elif action == "remotes":
            result = _run(["remote", "-v"], path, timeout)
        elif action == "fetch":
            result = _run(["fetch", "--prune", remote], path, timeout)
        elif action == "pull":
            args = ["pull", "--rebase" if tool_input.get("rebase", True) else "--ff-only", remote]
            if tool_input.get("branch"):
                args.append(str(tool_input["branch"]))
            result = _run(args, path, timeout)
        elif action == "push":
            branch = str(tool_input.get("branch") or "").strip()
            if not branch:
                current = _run(["branch", "--show-current"], path, timeout)
                branch = current["stdout"].strip()
            if not branch:
                raise ToolInputError("branch is required when HEAD is detached")
            if branch.lower() in {"main", "master"} and not bool(tool_input.get("allow_protected_branch")):
                raise ToolInputError("refusing to push main/master without allow_protected_branch=true; use a review branch")
            args = ["push"]
            if tool_input.get("set_upstream", True):
                args.append("--set-upstream")
            args += [remote, branch]
            result = _run(args, path, timeout)
            result["branch"] = branch
        else:
            raise ToolInputError(f"unsupported repository action: {action}")
        result["path"] = str(path)
        return ToolResult(name="Repository", output=result, is_error=result["exit_code"] != 0)
