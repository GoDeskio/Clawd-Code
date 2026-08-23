"""Sanitize tool schemas before they are sent to an LLM provider.

Anthropic requires every tool's input_schema to be a JSON Schema object
with a top-level ``type`` (typically ``object``). A missing type is a 400:

    tools.N.custom.input_schema.type: Field required

OpenAI-compatible providers also drop or reject schemas without ``type``.
This module repairs or drops every tool before the request is built.
ExternalAgent/MCP tools are omitted unless the user actually connected one.
"""

from __future__ import annotations

from typing import Any, Mapping

OPTIONAL_CONNECTOR_TOOLS = frozenset({
    "MCP",
    "ExternalAgent",
    "ListMcpResources",
    "ReadMcpResource",
})


def sanitize_input_schema(schema: Any) -> dict[str, Any] | None:
    """Return a JSON Schema object with type=object, or None if it cannot be repaired."""
    if schema is None:
        return {"type": "object", "properties": {}}
    if isinstance(schema, Mapping):
        out = dict(schema)
    else:
        return None

    raw_type = out.get("type")
    looks_like_object = any(
        key in out for key in ("properties", "required", "additionalProperties", "anyOf", "oneOf", "allOf")
    )
    if raw_type is None or raw_type in {"", "None"}:
        if looks_like_object or not out:
            out["type"] = "object"
        else:
            return None
    elif raw_type != "object" and not (isinstance(raw_type, list) and "object" in raw_type):
        if looks_like_object:
            out["type"] = "object"
        else:
            return None

    if out.get("type") == "object" and "properties" not in out and "anyOf" not in out and "oneOf" not in out:
        out["properties"] = {}
    return out


def sanitize_tool_payload(tool: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Repair one serialized tool, or drop it if it cannot be made valid."""
    if not isinstance(tool, Mapping):
        return None
    name = str(tool.get("name") or "").strip()
    if not name:
        return None
    schema = sanitize_input_schema(tool.get("input_schema"))
    if schema is None:
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
        if name in OPTIONAL_CONNECTOR_TOOLS and not include_optional_connectors:
            continue
        payload = sanitize_tool_payload({
            "name": name,
            "description": getattr(spec, "description", "") or "",
            "input_schema": getattr(spec, "input_schema", None),
        })
        if payload is not None:
            out.append(payload)
    return out
