from __future__ import annotations

from pathlib import Path
from typing import Any

from src.integrations.ecc import (
    ecc_cache_dir,
    import_catalog,
    memory_vault_export,
    memory_vault_import,
    security_scan,
    set_enabled,
    status,
    sync,
)
from src.skills.learning import analyze_git_history, learning_status, review_observations
from src.skills.library import save_user_skill

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class ECCIntegrationTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ECCIntegration",
            description=(
                "Index, audit, import, lazily enable, and update the MIT-licensed ECC skill/agent catalog; "
                "exchange inspectable memory-vault documents; and learn evidence-backed skills from Git history."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": [
                        "status", "sync", "scan", "import", "enable", "disable",
                        "memory_export", "memory_import", "learning_status", "review_observations", "analyze_git", "activate_draft",
                    ]},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "agents": {"type": "array", "items": {"type": "string"}},
                    "enable": {"type": "array", "items": {"type": "string"}},
                    "path": {"type": "string"},
                    "commits": {"type": "integer", "minimum": 1, "maximum": 2000},
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in {"status", "scan", "learning_status", "review_observations", "analyze_git"}:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(
            context,
            "ECCIntegration",
            f"{tool_input.get('action')} the managed ECC/learning library",
            "Allow ECC and learned-skill changes for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "status":
            output = status()
        elif action == "sync":
            output = sync()
        elif action == "scan":
            output = security_scan(ecc_cache_dir())
        elif action == "import":
            output = import_catalog(
                skill_names=tool_input.get("skills"),
                agent_names=tool_input.get("agents"),
                enable_names=tool_input.get("enable"),
            )
        elif action in {"enable", "disable"}:
            names = tool_input.get("skills") or []
            if not names:
                raise ToolInputError("skills is required")
            output = set_enabled(names, action == "enable")
        elif action == "memory_export":
            output = memory_vault_export()
        elif action == "memory_import":
            raw = str(tool_input.get("path") or "").strip()
            if not raw:
                raise ToolInputError("path is required")
            output = memory_vault_import(context.ensure_allowed_path(raw))
        elif action == "learning_status":
            output = learning_status(context.workspace_root)
        elif action == "review_observations":
            output = review_observations(context.workspace_root)
        elif action == "analyze_git":
            output = analyze_git_history(context.workspace_root, int(tool_input.get("commits") or 200))
        elif action == "activate_draft":
            name = str(tool_input.get("name") or "").strip()
            content = str(tool_input.get("content") or "")
            if not name or not content:
                raise ToolInputError("name and content are required; inspect the draft before activation")
            output = {"saved": save_user_skill(name, content), "learning": learning_status(context.workspace_root)}
        else:
            raise ToolInputError(f"unsupported ECC action: {action}")
        return ToolResult(name="ECCIntegration", output=output)
