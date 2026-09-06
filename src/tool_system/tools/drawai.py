"""Agent-facing raster-to-editable-artifact conversion tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.install.record import resolve_source_dir
from src.integrations.drawai import DrawAiManager
from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class DrawAiTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(name="EditableGraphics", description="Turn an uploaded raster diagram, paper figure, or slide screenshot into editable SVG and native-shape PPTX downloads using isolated local OCR, segmentation and background-removal models.",
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["status", "sync", "install", "convert"]},
                "image": {"type": "string"}, "output_dir": {"type": "string"},
                "device": {"type": "string", "enum": ["cpu", "gpu", "mps", "auto"]},
                "timeout": {"type": "integer", "minimum": 60, "maximum": 7200},
            }, "required": ["action"]}, is_destructive=True, max_result_size_chars=50_000, strict=True)

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") == "status":
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "EditableGraphics", "Install local vision models or create editable SVG/PPTX artifacts",
                                        "Allow editable-graphics work for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        manager = DrawAiManager(resolve_source_dir() or Path.cwd())
        action = str(tool_input["action"])
        if action == "status": output = manager.status()
        elif action == "sync": output = manager.sync()
        elif action == "install": output = manager.install(models=True, device=str(tool_input.get("device") or "cpu"))
        elif action == "convert":
            if not tool_input.get("image"): raise ToolInputError("image is required")
            source = context.ensure_allowed_path(str(tool_input["image"]))
            target = context.ensure_allowed_path(str(tool_input.get("output_dir") or f"media/editable-{source.stem}"))
            output = manager.convert(source, target, device=str(tool_input.get("device") or "cpu"), timeout=int(tool_input.get("timeout") or 7200))
            if context.artifact_publisher:
                published = [context.artifact_publisher(Path(path), Path(path).name) for path in output["artifacts"]]
                output["artifacts"] = published
        else: raise ToolInputError(f"Unsupported editable graphics action: {action}")
        return ToolResult(name="EditableGraphics", output=output)
