from __future__ import annotations

from typing import Any

from src.image_vision import compact_image_brief, inspect_image

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


class VisionAnalyzeTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="VisionAnalyze",
            aliases=("ImageInspect",),
            description=(
                "Read an image locally and report dimensions, dominant colors, brightness, sharpness, geometric "
                "shapes, people/faces, QR codes, and optional OCR text. Use it with the attached image pixels for "
                "dependable visual analysis before editing."
            ),
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {
                    "source": {"type": "string"},
                    "ocr": {"type": "boolean"},
                    "question": {"type": "string"},
                },
                "required": ["source"],
            },
            is_read_only=True,
            strict=True,
            max_result_size_chars=40_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        value = str(tool_input.get("source") or "").strip()
        if not value:
            raise ToolInputError("source is required")
        source = context.ensure_allowed_path(value)
        if not source.is_file():
            raise ToolInputError(f"image not found: {source}")
        result = inspect_image(source, run_ocr=bool(tool_input.get("ocr")))
        result["summary"] = compact_image_brief(result)
        if tool_input.get("question"):
            result["question"] = str(tool_input["question"])
        return ToolResult(name="VisionAnalyze", output=result)
