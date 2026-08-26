from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.skills.loader import get_all_skills, load_skills_from_dir
from src.skills.library import render_skill, save_user_skill, user_skill_library
from src.skills.curator import archive as archive_skill, pin as pin_skill, report as curator_report, restore as restore_skill

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _skill_root(scope: str, context: ToolContext) -> Path:
    return user_skill_library() if scope == "user" else (context.workspace_root / ".clawd" / "skills")


class SkillManagerTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="SkillManager",
            description=(
                "Create, update, validate, list, and package Jonathan Ai SKILL.md capabilities. "
                "Project skills travel with a repo; user skills persist across every conversation and project."
            ),
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "read", "create", "update", "validate", "package", "curator_status", "pin", "unpin", "archive", "restore"]},
                    "name": {"type": "string"}, "description": {"type": "string"}, "instructions": {"type": "string"},
                    "scope": {"type": "string", "enum": ["project", "user"]},
                    "allowed_tools": {"type": "array", "items": {"type": "string"}},
                    "when_to_use": {"type": "string"}, "version": {"type": "string"},
                    "user_invocable": {"type": "boolean"}, "output_name": {"type": "string"}
                },
                "required": ["action"]
            },
            is_destructive=True, max_result_size_chars=60_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in {"list", "read", "validate", "curator_status"}:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "SkillManager", f"{tool_input.get('action')} skill '{tool_input.get('name')}'",
                                        "Allow skill authoring for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        # Durable learning belongs in the shared visible library by default.
        # Project scope remains available when the workflow should travel only
        # with one repository.
        scope = str(tool_input.get("scope") or "user")
        root = _skill_root(scope, context)
        if action == "curator_status":
            return ToolResult(name="SkillManager", output={"skills": curator_report(), "archive": str(user_skill_library() / ".archive")})
        if action == "list":
            skills = get_all_skills(project_root=context.workspace_root)
            return ToolResult(name="SkillManager", output={"skills": [{
                "name": skill.name, "description": skill.description, "scope": skill.loaded_from,
                "path": str(Path(skill.skill_root) / "SKILL.md"), "version": skill.version,
                "allowed_tools": skill.allowed_tools,
            } for skill in skills]})
        name = str(tool_input.get("name") or "").strip().lower()
        if not _NAME.fullmatch(name):
            raise ToolInputError("name must be 2-64 lowercase letters, numbers, hyphens, or underscores")
        directory = root / name
        path = directory / "SKILL.md"
        if action in {"pin", "unpin", "archive", "restore"}:
            if scope != "user":
                raise ToolInputError("skill lifecycle actions are limited to user skills")
            try:
                result = pin_skill(name, action == "pin") if action in {"pin", "unpin"} else (archive_skill(name) if action == "archive" else restore_skill(name))
            except ValueError as exc:
                raise ToolInputError(str(exc)) from exc
            return ToolResult(name="SkillManager", output=result)
        if action == "read":
            if not path.is_file():
                raise ToolInputError(f"skill not found: {path}")
            return ToolResult(name="SkillManager", output={
                "name": name, "scope": scope, "path": str(path),
                "content": path.read_text(encoding="utf-8"),
            })
        if action in {"create", "update"}:
            exists = path.exists()
            if action == "create" and exists:
                raise ToolInputError(f"skill already exists: {path}; use update")
            if action == "update" and not exists:
                raise ToolInputError(f"skill does not exist: {path}; use create")
            description = str(tool_input.get("description") or "").strip()
            instructions = str(tool_input.get("instructions") or "").strip()
            if not description or not instructions:
                raise ToolInputError("description and instructions are required")
            allowed = [str(item) for item in tool_input.get("allowed_tools") or []]
            content = render_skill(
                name=name,
                description=description,
                instructions=instructions,
                version=str(tool_input.get("version") or "1.0.0"),
                when_to_use=str(tool_input.get("when_to_use") or ""),
                allowed_tools=allowed,
                user_invocable=bool(tool_input.get("user_invocable", True)),
            )
            if scope == "user":
                saved = save_user_skill(name, content)
                path = Path(saved["path"])
            else:
                directory.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
            loaded = load_skills_from_dir(root, loaded_from=scope)
            match = next((skill for skill in loaded if skill.name == name), None)
            if not match:
                raise ToolInputError("the generated SKILL.md could not be loaded")
            return ToolResult(name="SkillManager", output={"action": action, "name": name, "scope": scope,
                "path": str(path), "library": str(root), "valid": True, "description": match.description})
        if not path.is_file():
            raise ToolInputError(f"skill not found: {path}")
        if action == "validate":
            loaded = load_skills_from_dir(root, loaded_from=scope)
            match = next((skill for skill in loaded if skill.name == name), None)
            return ToolResult(name="SkillManager", output={"name": name, "path": str(path), "valid": bool(match),
                "description": match.description if match else None, "allowed_tools": match.allowed_tools if match else []}, is_error=match is None)
        if action == "package":
            if context.artifact_publisher is None:
                raise ToolInputError("artifact publishing is unavailable in this host")
            artifact = context.artifact_publisher(directory, str(tool_input.get("output_name") or f"{name}-skill.zip"))
            return ToolResult(name="SkillManager", output={"name": name, "path": str(directory), "artifact": artifact, "artifacts": [artifact]})
        raise ToolInputError(f"unsupported skill action: {action}")
