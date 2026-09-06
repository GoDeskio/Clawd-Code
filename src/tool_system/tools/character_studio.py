from __future__ import annotations
from pathlib import Path
from typing import Any
from src.integrations.character_studio import generate_character
from ..context import ToolContext
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec

class CharacterStudioTool:
    def spec(self)->ToolSpec:
        return ToolSpec(name="CharacterStudio",description="Generate deterministic, editable, animated procedural character SVG and rig-recipe JSON assets without an API, model, or external repository.",input_schema={"type":"object","additionalProperties":False,"properties":{"seed":{"type":"string"},"name":{"type":"string"},"species":{"type":"string","enum":["auto","human","cat","dog","fox","rabbit","bear"]},"medium":{"type":"string","enum":["ink","chalk","marker","watercolor"]},"output_dir":{"type":"string"}}},is_destructive=True,max_result_size_chars=20000,strict=True)
    def check_permissions(self,tool_input:dict[str,Any],context:ToolContext)->PermissionResult:
        return maybe_ask_for_gated_tool(context,"CharacterStudio","Write editable character SVG and JSON files","Allow character generation for the rest of this session")
    def run(self,tool_input:dict[str,Any],context:ToolContext)->ToolResult:
        target=context.ensure_allowed_path(str(tool_input.get("output_dir") or "media/characters")); output=generate_character(target,seed=str(tool_input.get("seed") or "jonathan"),name=str(tool_input.get("name") or ""),species=str(tool_input.get("species") or "auto"),medium=str(tool_input.get("medium") or "ink"))
        if context.artifact_publisher: output["artifacts"]=[context.artifact_publisher(Path(path),Path(path).name) for path in output["artifacts"]]
        return ToolResult(name="CharacterStudio",output=output)
