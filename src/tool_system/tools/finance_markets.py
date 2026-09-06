from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


def _yf() -> Any:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ToolExecutionError("Market data dependencies are missing; restart Jonathan Ai to auto-install them") from exc
    return yf


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def _history(symbol: str, period: str, interval: str) -> list[dict[str, Any]]:
    try:
        frame = _yf().Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    except Exception as exc:
        raise ToolExecutionError(f"market data failed for {symbol}: {exc}") from exc
    rows = []
    for index, row in frame.iterrows():
        rows.append({"timestamp": _clean(index), **{str(key).lower().replace(" ", "_"): _clean(value) for key, value in row.items()}})
    return rows


def _quote(symbol: str) -> dict[str, Any]:
    rows = _history(symbol, "5d", "1d")
    if not rows:
        return {"symbol": symbol, "error": "no market data returned"}
    last = rows[-1]
    previous = rows[-2] if len(rows) > 1 else last
    price = last.get("close")
    previous_close = previous.get("close")
    change = (float(price) - float(previous_close)) if price is not None and previous_close is not None else None
    return {"symbol": symbol.upper(), "price": price, "previous_close": previous_close, "change": change,
            "change_percent": (change / float(previous_close) * 100) if change is not None and previous_close else None,
            "open": last.get("open"), "high": last.get("high"), "low": last.get("low"), "volume": last.get("volume"),
            "currency": None, "market_time": last.get("timestamp"), "source": "Yahoo Finance"}


class FinanceMarketsTool:
    def spec(self) -> ToolSpec:
        position = {"type": "object", "additionalProperties": False, "properties": {
            "symbol": {"type": "string"}, "quantity": {"type": "number"}, "cost_basis": {"type": "number"}
        }, "required": ["symbol", "quantity"]}
        return ToolSpec(
            name="FinanceMarkets",
            description=(
                "Fetch current/delayed market quotes and history, calculate technical indicators, screen symbols, value a portfolio, "
                "or monitor a watchlist into a downloadable report. Market data is informational and may be delayed."
            ),
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["quote", "history", "technical", "screen", "portfolio", "monitor"]},
                "symbol": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                "positions": {"type": "array", "items": position, "maxItems": 500}, "period": {"type": "string"},
                "interval": {"type": "string"}, "duration": {"type": "number", "minimum": 1, "maximum": 300},
                "poll_interval": {"type": "number", "minimum": 1, "maximum": 60}, "output": {"type": "string"}
            }, "required": ["action"]},
            is_destructive=True, max_result_size_chars=150_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") != "monitor":
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "FinanceMarkets", "Monitor live market data and write a downloadable report",
                                        "Allow market monitoring for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        symbol = str(tool_input.get("symbol") or "").strip().upper()
        symbols = [str(item).strip().upper() for item in tool_input.get("symbols") or [] if str(item).strip()]
        disclaimer = "Informational market data; may be delayed or incomplete. This tool does not provide investment advice."
        if action == "quote":
            if not symbol:
                raise ToolInputError("symbol is required")
            return ToolResult(name="FinanceMarkets", output={"quote": _quote(symbol), "disclaimer": disclaimer})
        if action == "history":
            if not symbol:
                raise ToolInputError("symbol is required")
            return ToolResult(name="FinanceMarkets", output={"symbol": symbol, "rows": _history(symbol, str(tool_input.get("period") or "1mo"), str(tool_input.get("interval") or "1d")), "disclaimer": disclaimer})
        if action == "technical":
            if not symbol:
                raise ToolInputError("symbol is required")
            rows = _history(symbol, str(tool_input.get("period") or "6mo"), str(tool_input.get("interval") or "1d"))
            closes = [float(row["close"]) for row in rows if row.get("close") is not None]
            if len(closes) < 15:
                raise ToolExecutionError("not enough history to calculate indicators")
            gains = [max(0.0, b - a) for a, b in zip(closes[-15:-1], closes[-14:])]
            losses = [max(0.0, a - b) for a, b in zip(closes[-15:-1], closes[-14:])]
            avg_gain, avg_loss = sum(gains) / 14, sum(losses) / 14
            rsi = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
            return ToolResult(name="FinanceMarkets", output={"symbol": symbol, "price": closes[-1],
                "sma_20": sum(closes[-20:]) / min(20, len(closes)), "sma_50": sum(closes[-50:]) / min(50, len(closes)),
                "rsi_14": rsi, "observations": len(closes), "disclaimer": disclaimer})
        if action == "screen":
            if not symbols:
                raise ToolInputError("symbols is required")
            return ToolResult(name="FinanceMarkets", output={"quotes": [_quote(item) for item in symbols], "disclaimer": disclaimer})
        if action == "portfolio":
            positions = list(tool_input.get("positions") or [])
            if not positions:
                raise ToolInputError("positions is required")
            valued, total_value, total_cost = [], 0.0, 0.0
            for position in positions:
                quote = _quote(str(position["symbol"]).upper())
                quantity = float(position["quantity"])
                price = float(quote.get("price") or 0)
                value = quantity * price
                cost = quantity * float(position.get("cost_basis") or 0)
                total_value += value; total_cost += cost
                valued.append({**position, "symbol": str(position["symbol"]).upper(), "price": price, "market_value": value,
                               "cost": cost, "unrealized_pl": value - cost if position.get("cost_basis") is not None else None})
            return ToolResult(name="FinanceMarkets", output={"positions": valued, "market_value": total_value,
                "cost": total_cost, "unrealized_pl": total_value - total_cost, "disclaimer": disclaimer})
        if action == "monitor":
            if not symbols:
                raise ToolInputError("symbols is required")
            duration, interval = float(tool_input.get("duration") or 30), float(tool_input.get("poll_interval") or 10)
            samples, deadline = [], time.monotonic() + duration
            while True:
                samples.append({"captured_at": datetime.now(timezone.utc).isoformat(), "quotes": [_quote(item) for item in symbols]})
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(interval, remaining))
            output = context.ensure_allowed_path(str(tool_input.get("output") or "finance/market-monitor.json"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"symbols": symbols, "samples": samples, "disclaimer": disclaimer}, indent=2, ensure_ascii=False), encoding="utf-8")
            artifacts = [context.artifact_publisher(output, output.name)] if context.artifact_publisher else []
            return ToolResult(name="FinanceMarkets", output={"path": str(output), "sample_count": len(samples), "samples": samples,
                "artifact": artifacts[0] if artifacts else None, "artifacts": artifacts, "disclaimer": disclaimer})
        raise ToolInputError(f"unsupported market action: {action}")
