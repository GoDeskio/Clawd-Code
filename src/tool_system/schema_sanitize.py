"""Sanitize tool schemas before they are sent to an LLM provider.

Anthropic requires every tool's input_schema to be a JSON Schema object
with a top-level ``type`` (typically ``object``). A missing type is a 400:

    tools.N.custom.input_schema.type: Field required

The live 0.2.0 payload still 400'd at tools.17 because (1) MCP resource tools
were not omitted (their real names are ListMcpResourcesTool / ReadMcpResourceTool)
and (2) the Anthropic SDK/API can reject or drop non-classic schemas. This
module always emits the classic shape and can flatten anyOf/oneOf.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

OPTIONAL_CONNECTOR_TOOLS = frozenset({
    "MCP",
    "ExternalAgent",
    "ListMcpResources",
    "ReadMcpResource",
    "ListMcpResourcesTool",
    "ReadMcpResourceTool",
})


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return value


def _is_optional_connector_name(name: str) -> bool:
    raw = str(name or "").strip()
    if raw in OPTIONAL_CONNECTOR_TOOLS:
        return True
    lowered = raw.lower()
    if lowered.startswith("externalagent"):
        return True
    return "mcp" in lowered


def _flatten_combinators(node: dict[str, Any]) -> dict[str, Any]:
    """Merge anyOf/oneOf/allOf object variants into one object schema."""
    variants: list[Any] = []
    for key in ("anyOf", "oneOf", "allOf"):
        items = node.pop(key, None)
        if isinstance(items, list):
            variants.extend(items)
    if not variants:
        return node
    props = dict(node.get("properties") or {})
    required: list[str] = list(node.get("required") or [])
    for variant in variants:
        if not isinstance(variant, Mapping):
            continue
        child = dict(variant)
        child = _flatten_combinators(child)
        for key, value in (child.get("properties") or {}).items():
            props.setdefault(key, value)
        for item in child.get("required") or []:
            text = str(item)
            if text not in required:
                required.append(text)
    if props and "properties" not in node:
        node["properties"] = props
    elif props:
        merged = dict(node.get("properties") or {})
        merged.update(props)
        node["properties"] = merged
    if required and "required" not in node:
        node["required"] = required
    node.setdefault("type", "object")
    return node


def classic_schema_node(schema: Any) -> dict[str, Any]:
    """Recursively produce a JSON Schema node; every object has type=object."""
    if schema is None:
        return {"type": "object", "properties": {}}
    if not isinstance(schema, Mapping):
        return {"type": "object", "properties": {}}
    node = _flatten_combinators(dict(schema))
    raw_type = node.get("type")
    has_items = "items" in node
    looks_object = any(
        key in node for key in ("properties", "required", "additionalProperties")
    )
    if raw_type is None or raw_type in {"", "None"}:
        node["type"] = "array" if has_items and not looks_object else "object"
    elif isinstance(raw_type, list):
        node["type"] = "object" if "object" in raw_type else raw_type[0]
    if node.get("type") == "object":
        props = node.get("properties")
        if not isinstance(props, dict):
            props = {}
        node["properties"] = {
            str(key): classic_schema_node(value) if isinstance(value, Mapping) else value
            for key, value in props.items()
        }
    if "items" in node and isinstance(node["items"], Mapping):
        node["items"] = classic_schema_node(node["items"])
    additional = node.get("additionalProperties")
    if isinstance(additional, Mapping):
        node["additionalProperties"] = classic_schema_node(additional)
    return node


def classic_input_schema(schema: Any) -> dict[str, Any] | None:
    """Classic Anthropic input_schema: type=object, properties, optional required."""
    node = classic_schema_node(schema)
    if not isinstance(node, dict):
        return None
    props = node.get("properties")
    if not isinstance(props, dict):
        props = {}
    out: dict[str, Any] = {"type": "object", "properties": props}
    required = node.get("required")
    if isinstance(required, list) and required:
        out["required"] = [str(item) for item in required]
    return _json_copy(out)


def sanitize_input_schema(schema: Any) -> dict[str, Any] | None:
    """Return a JSON Schema object with type=object, or None if it cannot be repaired."""
    return classic_input_schema(schema)


def sanitize_tool_payload(tool: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Classic Anthropic tool: {name, description, input_schema:{type, properties, required?}}."""
    if not isinstance(tool, Mapping):
        return None
    name = str(tool.get("name") or "").strip()
    if not name:
        return None
    schema = classic_input_schema(tool.get("input_schema"))
    if schema is None or schema.get("type") != "object":
        return None
    return {
        "name": name,
        "description": str(tool.get("description") or ""),
        "input_schema": schema,
    }


def sanitize_tools_for_api(tools: Any) -> list[dict[str, Any]]:
    """Sanitize a list of already-serialized tools for Anthropic/OpenAI."""
    if not tools:
        return []
    out: list[dict[str, Any]] = []
    for tool in tools:
        payload = sanitize_tool_payload(tool)
        if payload is not None:
            out.append(payload)
    return out


def prepare_anthropic_tools(tools: Any) -> list[dict[str, Any]]:
    """Tools in the only shape Anthropic messages.create should receive."""
    return sanitize_tools_for_api(tools)


def describe_tool_at_index(tools: Any, index: int = 17) -> str:
    rows = list(tools or [])
    if index >= len(rows):
        return f"index {index} out of range ({len(rows)} tools)"
    tool = rows[index] if isinstance(rows[index], Mapping) else {}
    schema = tool.get("input_schema") if isinstance(tool, Mapping) else None
    schema_type = schema.get("type") if isinstance(schema, Mapping) else None
    name = tool.get("name") if isinstance(tool, Mapping) else "?"
    return f"index {index} name={name!r} input_schema.type={schema_type!r} schema_keys={list(schema.keys()) if isinstance(schema, Mapping) else None}"


def is_input_schema_type_error(exc: BaseException) -> bool:
    """True for Anthropic 400: tools.N.custom.input_schema.type: Field required."""
    text = str(exc)
    lowered = text.lower()
    if "input_schema.type" in text:
        return True
    body = getattr(exc, "body", None)
    if isinstance(body, Mapping):
        error = body.get("error") if isinstance(body.get("error"), Mapping) else body
        message = str(error.get("message") or "")
        err_type = str(error.get("type") or "")
        if "input_schema.type" in message:
            return True
        if err_type == "invalid_request_error" and "input_schema" in message and "type" in message:
            return True
    if "invalid_request_error" in lowered and "input_schema" in lowered and "field required" in lowered:
        return True
    return False


def log_rejected_tool_index(tools: Any, exc: BaseException, index: int = 17) -> None:
    logger.error(
        "Anthropic rejected tool schemas (%s). Offending %s. Retrying the same request without tools.",
        exc,
        describe_tool_at_index(tools, index),
    )


def connectors_are_connected(tool_context: Any | None = None) -> bool:
    """True only when the user connected an MCP server or another agent."""
    if tool_context is not None:
        clients = getattr(tool_context, "mcp_clients", None)
        if isinstance(clients, dict) and clients:
            return True
    try:
        from src.connectors.store import read_connectors

        data = read_connectors()
    except Exception:
        return False
    for item in data.get("mcp") or []:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        if item.get("command") or item.get("url"):
            return True
    for item in data.get("agents") or []:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        if item.get("base_url"):
            return True
    return False


def serialize_tools_for_provider(
    registry: Any,
    *,
    include_optional_connectors: bool | None = None,
    tool_context: Any | None = None,
) -> list[dict[str, Any]]:
    """Build the provider tool list from a registry.

    Optional ExternalAgent/MCP tools are omitted when nothing is connected so a
    first-run chat with only a provider key or local LLM does not depend on
    Cursor, Codex, or any other agent.
    """
    if include_optional_connectors is None:
        include_optional_connectors = connectors_are_connected(tool_context)
    out: list[dict[str, Any]] = []
    specs = registry.list_specs() if hasattr(registry, "list_specs") else []
    for spec in specs:
        name = getattr(spec, "name", "")
        if _is_optional_connector_name(name) and not include_optional_connectors:
            continue
        payload = sanitize_tool_payload({
            "name": name,
            "description": getattr(spec, "description", "") or "",
            "input_schema": getattr(spec, "input_schema", None),
        })
        if payload is not None:
            out.append(payload)
    return out
