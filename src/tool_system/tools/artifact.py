from __future__ import annotations

from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class ArtifactTool:
    """Publish any workspace file or directory to the desktop download shelf."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Artifact",
            description=(
                "Make any file downloadable from the conversation. Directories are packaged as ZIP files. "
                "Use this after creating a document, archive, image, model, executable, or other deliverable."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Workspace file or directory to publish."},
                    "name": {"type": "string", "description": "Optional download filename."},
                },
                "required": ["path"],
            },
            is_destructive=True,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        return maybe_ask_for_gated_tool(
            context,
            "Artifact",
            f"Publish a downloadable copy of {tool_input.get('path')}",
            "Allow Artifact publishing for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        path = context.ensure_allowed_path(str(tool_input["path"]))
        if not path.exists():
            raise ToolInputError(f"file or directory not found: {path}")
        if context.artifact_publisher is None:
            raise ToolInputError("artifact publishing is unavailable in this host")
        preferred = str(tool_input.get("name") or "").strip() or None
        artifact = context.artifact_publisher(path, preferred)
        return ToolResult(
            name="Artifact",
            output={"path": str(path), "artifact": artifact, "artifacts": [artifact]},
        )
