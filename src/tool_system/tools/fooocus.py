"""Agent-facing lifecycle and artifact bridge for Jonathan local images."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.install.record import resolve_source_dir
from src.integrations.fooocus import FooocusManager

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


class FooocusTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="LocalImage",
            description=(
                "Manage Jonathan's built-in local diffusion image engine. Verify dependencies, generate images, "
                "list outputs, and publish the latest image as a conversation download."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "install", "start", "stop", "generate", "list_outputs", "publish_latest"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                    "width": {"type": "integer", "minimum": 256, "maximum": 2048},
                    "height": {"type": "integer", "minimum": 256, "maximum": 2048},
                    "performance": {"type": "string", "enum": ["Speed", "Quality", "Extreme Speed", "Lightning", "Hyper-SD"]},
                    "seed": {"type": "integer", "minimum": 0},
                },
                "required": ["action"],
            },
            is_destructive=True,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "status")
        return maybe_ask_for_gated_tool(
            context,
            "LocalImage",
            f"Run local image action '{action}' on this computer",
            "Allow local image generation for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        source = resolve_source_dir() or Path.cwd()
        manager = FooocusManager(source)
        action = str(tool_input["action"])
        if action == "status":
            output: dict[str, Any] = manager.status()
        elif action == "install":
            output = manager.install()
        elif action == "start":
            output = manager.start()
        elif action == "stop":
            output = manager.stop()
        elif action == "generate":
            output = manager.generate(
                str(tool_input.get("prompt") or ""),
                negative_prompt=str(tool_input.get("negative_prompt") or ""),
                width=int(tool_input.get("width") or 1024),
                height=int(tool_input.get("height") or 1024),
                performance=str(tool_input.get("performance") or "Speed"),
                seed=int(tool_input["seed"]) if tool_input.get("seed") is not None else None,
            )
            if context.artifact_publisher is not None:
                artifacts = [context.artifact_publisher(item["path"], item["name"]) for item in output["outputs"]]
                output["artifact"] = artifacts[0]
                output["artifacts"] = artifacts
        elif action == "list_outputs":
            output = {"outputs": manager.latest_outputs(int(tool_input.get("limit") or 20)), **manager.status()}
        elif action == "publish_latest":
            latest = manager.latest_outputs(1)
            if not latest:
                raise ToolInputError("Jonathan's local engine has not generated an image yet")
            if context.artifact_publisher is None:
                raise ToolInputError("artifact publishing is unavailable in this host")
            artifact = context.artifact_publisher(latest[0]["path"], latest[0]["name"])
            output = {"path": latest[0]["path"], "artifact": artifact, "artifacts": [artifact]}
        else:  # pragma: no cover - schema validation catches this
            raise ToolInputError(f"unsupported local image action: {action}")
        return ToolResult(name="LocalImage", output=output)
