"""Agent-facing lifecycle control for the isolated personal finance vault."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.install.record import resolve_source_dir
from src.integrations.securo import SecuroManager

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class PersonalFinanceVaultTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="PersonalFinanceVault",
            description=("Manage Jonathan's native local personal-finance vault: accounts, transactions, categories, recurring items, "
                         "budgets, goals, assets, reports and currencies. No container, cloned application, payment, subscription, or trade execution is required."),
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["status", "install", "add_account", "add_transaction", "list", "dashboard"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                "entity": {"type": "string", "enum": ["accounts", "transactions", "budgets", "goals", "assets"]},
                "name": {"type": "string"}, "type": {"type": "string"}, "account_id": {"type": "string"},
                "amount": {"type": "number"}, "currency": {"type": "string"}, "category": {"type": "string"},
                "description": {"type": "string"}, "occurred_on": {"type": "string"}, "recurring": {"type": "boolean"},
            }, "required": ["action"]},
            is_destructive=True, max_result_size_chars=50_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in {"status", "list", "dashboard"}:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "PersonalFinanceVault",
                                        f"Run isolated finance service action '{tool_input.get('action')}'",
                                        "Allow personal finance service management for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        manager = SecuroManager(resolve_source_dir() or Path.cwd())
        action = str(tool_input["action"])
        if action == "status": output: dict[str, Any] = manager.status()
        elif action == "install": output = manager.install()
        elif action in {"add_account", "add_transaction", "list", "dashboard"}: output = manager.action(action, **{key: value for key, value in tool_input.items() if key != "action"})
        else: raise ToolInputError(f"unsupported personal finance action: {action}")
        return ToolResult(name="PersonalFinanceVault", output=output)
