"""Default registry tools must serialize with a valid JSON Schema type."""

from __future__ import annotations

import unittest

from src.tool_system.defaults import build_default_registry
from src.tool_system.schema_sanitize import (
    OPTIONAL_CONNECTOR_TOOLS,
    connectors_are_connected,
    sanitize_input_schema,
    sanitize_tools_for_api,
    serialize_tools_for_provider,
)
from src.tool_system.tools.skill import SkillTool


class TestToolSchemaSanitizer(unittest.TestCase):
    def test_default_registry_serialized_schemas_have_type(self) -> None:
        registry = build_default_registry(include_user_tools=False)
        specs = registry.list_specs()
        self.assertGreaterEqual(len(specs), 18)
        self.assertEqual(specs[17].name, "Skill")

        tools = serialize_tools_for_provider(registry, include_optional_connectors=True)
        self.assertTrue(tools)
        for tool in tools:
            schema = tool["input_schema"]
            self.assertIsInstance(schema, dict, tool["name"])
            self.assertEqual(schema.get("type"), "object", tool["name"])
            names = [item["name"] for item in tools]
        self.assertIn("Skill", names)
        skill = next(item for item in tools if item["name"] == "Skill")
        self.assertEqual(skill["input_schema"]["type"], "object")

    def test_optional_connector_tools_omitted_when_nothing_connected(self) -> None:
        registry = build_default_registry(include_user_tools=False)
        tools = serialize_tools_for_provider(registry, include_optional_connectors=False)
        names = {item["name"] for item in tools}
        self.assertTrue(OPTIONAL_CONNECTOR_TOOLS.isdisjoint(names))
        self.assertIn("Skill", names)
        self.assertIn("Bash", names)
        for tool in tools:
            self.assertEqual(tool["input_schema"].get("type"), "object")

    def test_repairs_anyof_schema_missing_type(self) -> None:
        broken = {
            "anyOf": [
                {"type": "object", "properties": {"skill": {"type": "string"}}},
            ]
        }
        repaired = sanitize_input_schema(broken)
        self.assertIsNotNone(repaired)
        self.assertEqual(repaired["type"], "object")
        payload = sanitize_tools_for_api([
            {"name": "Skill", "description": "x", "input_schema": broken},
            {"name": "", "input_schema": {"type": "object"}},
            {"description": "no name"},
        ])
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["input_schema"]["type"], "object")

    def test_skill_tool_spec_has_object_type(self) -> None:
        schema = dict(SkillTool().spec().input_schema)
        self.assertEqual(schema.get("type"), "object")

    def test_connectors_are_connected_false_without_config(self) -> None:
        self.assertFalse(connectors_are_connected(type("Ctx", (), {"mcp_clients": {}})()))
        self.assertTrue(connectors_are_connected(type("Ctx", (), {"mcp_clients": {"docs": object()}})()))


if __name__ == "__main__":
    unittest.main()
