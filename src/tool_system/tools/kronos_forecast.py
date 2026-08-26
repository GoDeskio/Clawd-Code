"""Agent-facing Kronos financial-market forecasting tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.install.record import resolve_source_dir
from src.integrations.kronos import KronosManager

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class KronosForecastTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="KronosForecast",
            description=("Run local market-specific probabilistic OHLCV forecasts from a CSV using the MIT Kronos model. "
                         "Outputs a downloadable CSV for research and backtesting; never places trades."),
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["status", "install", "forecast"]},
                "input_csv": {"type": "string"}, "output_csv": {"type": "string"},
                "model": {"type": "string", "enum": ["mini", "small", "base"]},
                "pred_len": {"type": "integer", "minimum": 1, "maximum": 256},
                "lookback": {"type": "integer", "minimum": 16, "maximum": 2048},
                "sample_count": {"type": "integer", "minimum": 1, "maximum": 20},
                "temperature": {"type": "number", "exclusiveMinimum": 0, "maximum": 5},
                "top_p": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                "timeout": {"type": "integer", "minimum": 30, "maximum": 3600},
            }, "required": ["action"]},
            is_destructive=True, max_result_size_chars=50_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") == "status":
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "KronosForecast", "Download/run Kronos locally and write a research forecast",
                                        "Allow Kronos forecasting for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        manager = KronosManager(resolve_source_dir() or Path.cwd())
        action = str(tool_input["action"])
        if action == "status":
            output: dict[str, Any] = manager.status()
        elif action == "install":
            output = manager.install()
        elif action == "forecast":
            if not tool_input.get("input_csv"):
                raise ToolInputError("input_csv is required")
            source = context.ensure_allowed_path(str(tool_input["input_csv"]))
            target = context.ensure_allowed_path(str(tool_input.get("output_csv") or f"finance/kronos-{source.stem}-forecast.csv"))
            output = manager.forecast(source, target, model=str(tool_input.get("model") or "mini"),
                                      pred_len=int(tool_input.get("pred_len") or 24), lookback=int(tool_input.get("lookback") or 400),
                                      sample_count=int(tool_input.get("sample_count") or 1),
                                      temperature=float(tool_input.get("temperature") or 1.0), top_p=float(tool_input.get("top_p") or 0.9),
                                      timeout=int(tool_input.get("timeout") or 1800))
            if context.artifact_publisher:
                artifact = context.artifact_publisher(target, target.name)
                output.update({"artifact": artifact, "artifacts": [artifact]})
        else:
            raise ToolInputError(f"unsupported Kronos action: {action}")
        return ToolResult(name="KronosForecast", output=output)
