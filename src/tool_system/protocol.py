from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]
    tool_use_id: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    name: str
    output: Any
    is_error: bool = False
    tool_use_id: Optional[str] = None
    content_type: Literal["text", "json"] = "json"

    def __post_init__(self) -> None:
        from ..secret_mask import mask_tool_output

        object.__setattr__(self, "output", mask_tool_output(self.output))

