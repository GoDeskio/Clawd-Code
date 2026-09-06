from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from src.config import get_finance_config, set_alpaca_config

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


def _alpaca() -> dict[str, Any]:
    slot = get_finance_config().get("alpaca") or {}
    if not isinstance(slot, dict) or not slot.get("api_key") or not slot.get("secret_key"):
        raise ToolInputError("Alpaca is not configured; run Trading action=configure with paper=true first")
    return slot


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    config = _alpaca()
    base = "https://paper-api.alpaca.markets" if config.get("paper", True) else "https://api.alpaca.markets"
    request = urllib.request.Request(base + path, method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"APCA-API-KEY-ID": str(config["api_key"]), "APCA-API-SECRET-KEY": str(config["secret_key"]), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {"success": True}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:3000]
        raise ToolExecutionError(f"broker returned HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ToolExecutionError(f"broker request failed: {exc}") from exc


class TradingTool:
    READ_ONLY = {"status", "account", "positions", "orders"}

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Trading",
            description=(
                "Connect an Alpaca paper or live brokerage account; inspect account, positions, and orders; submit or cancel orders. "
                "Paper mode is the default. Every order-changing action requires fresh user approval and is audit logged."
            ),
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["configure", "status", "account", "positions", "orders", "submit_order", "cancel_order"]},
                "api_key": {"type": "string"}, "secret_key": {"type": "string"}, "paper": {"type": "boolean"},
                "symbol": {"type": "string"}, "quantity": {"type": "number", "exclusiveMinimum": 0}, "notional": {"type": "number", "exclusiveMinimum": 0},
                "side": {"type": "string", "enum": ["buy", "sell"]}, "order_type": {"type": "string", "enum": ["market", "limit", "stop", "stop_limit", "trailing_stop"]},
                "time_in_force": {"type": "string", "enum": ["day", "gtc", "opg", "cls", "ioc", "fok"]},
                "limit_price": {"type": "number", "exclusiveMinimum": 0}, "stop_price": {"type": "number", "exclusiveMinimum": 0},
                "trail_price": {"type": "number", "exclusiveMinimum": 0}, "trail_percent": {"type": "number", "exclusiveMinimum": 0},
                "extended_hours": {"type": "boolean"}, "client_order_id": {"type": "string"}, "order_id": {"type": "string"},
                "status_filter": {"type": "string", "enum": ["open", "closed", "all"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}
            }, "required": ["action"]},
            is_destructive=True, max_result_size_chars=100_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "")
        if action in self.READ_ONLY:
            return PermissionResult.allow()
        if action in {"submit_order", "cancel_order"}:
            config = get_finance_config().get("alpaca") or {}
            mode = "PAPER" if config.get("paper", True) else "LIVE — REAL MONEY"
            detail = f"{tool_input.get('side','')} {tool_input.get('quantity') or tool_input.get('notional','')} {tool_input.get('symbol','')}".strip()
            return PermissionResult.ask(f"Confirm {mode} broker action {action}: {detail}. This approval applies only to this order.")
        return maybe_ask_for_gated_tool(context, "Trading", "Save broker credentials locally (secrets are hidden from UI and audit logs)",
                                        "Allow broker configuration for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "configure":
            api_key, secret_key = str(tool_input.get("api_key") or "").strip(), str(tool_input.get("secret_key") or "").strip()
            if not api_key or not secret_key:
                raise ToolInputError("api_key and secret_key are required")
            configured = set_alpaca_config(api_key, secret_key, paper=bool(tool_input.get("paper", True)))
            return ToolResult(name="Trading", output={**configured, "provider": "alpaca", "message": "Credentials saved locally; secrets are not returned"})
        if action == "status":
            slot = get_finance_config().get("alpaca") or {}
            return ToolResult(name="Trading", output={"provider": "alpaca", "configured": bool(slot.get("api_key") and slot.get("secret_key")),
                "paper": bool(slot.get("paper", True)), "mode": "paper" if slot.get("paper", True) else "live"})
        if action == "account":
            return ToolResult(name="Trading", output={"account": _request("GET", "/v2/account")})
        if action == "positions":
            return ToolResult(name="Trading", output={"positions": _request("GET", "/v2/positions")})
        if action == "orders":
            status = str(tool_input.get("status_filter") or "open")
            limit = int(tool_input.get("limit") or 100)
            return ToolResult(name="Trading", output={"orders": _request("GET", f"/v2/orders?status={status}&limit={limit}&direction=desc")})
        if action == "submit_order":
            symbol, side = str(tool_input.get("symbol") or "").upper(), str(tool_input.get("side") or "")
            if not symbol or side not in {"buy", "sell"} or not (tool_input.get("quantity") or tool_input.get("notional")):
                raise ToolInputError("symbol, side, and quantity or notional are required")
            payload = {"symbol": symbol, "side": side, "type": str(tool_input.get("order_type") or "market"),
                       "time_in_force": str(tool_input.get("time_in_force") or "day"), "extended_hours": bool(tool_input.get("extended_hours", False))}
            mapping = {"quantity": "qty", "notional": "notional", "limit_price": "limit_price", "stop_price": "stop_price",
                       "trail_price": "trail_price", "trail_percent": "trail_percent", "client_order_id": "client_order_id"}
            for source, target in mapping.items():
                if tool_input.get(source) is not None:
                    payload[target] = tool_input[source]
            return ToolResult(name="Trading", output={"order": _request("POST", "/v2/orders", payload),
                "mode": "paper" if _alpaca().get("paper", True) else "live"})
        if action == "cancel_order":
            order_id = str(tool_input.get("order_id") or "").strip()
            if not order_id:
                raise ToolInputError("order_id is required")
            return ToolResult(name="Trading", output={"order_id": order_id, "cancelled": _request("DELETE", f"/v2/orders/{order_id}"),
                "mode": "paper" if _alpaca().get("paper", True) else "live"})
        raise ToolInputError(f"unsupported trading action: {action}")
