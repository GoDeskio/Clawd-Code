"""Anthropic messages.create must receive classic tools with input_schema.type."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.providers.anthropic_provider import AnthropicProvider
from src.providers.base import ChatMessage, ChatResponse
from src.tool_system.defaults import build_default_registry
from src.tool_system.schema_sanitize import (
    is_input_schema_type_error,
    prepare_anthropic_tools,
    serialize_tools_for_provider,
)
from src.tool_system.tools.ask_user_question import AskUserQuestionTool


def _ok_response() -> MagicMock:
    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = "ok"
    mock_response.content = [mock_text_block]
    mock_response.model = "claude-sonnet-4-6"
    mock_response.usage = MagicMock(input_tokens=3, output_tokens=2)
    mock_response.stop_reason = "end_turn"
    return mock_response


class TestAnthropicClassicToolPayload(unittest.TestCase):
    def test_messages_create_payload_has_type_on_every_tool(self) -> None:
        registry = build_default_registry(include_user_tools=False)
        tools = serialize_tools_for_provider(registry, include_optional_connectors=False)
        self.assertGreaterEqual(len(tools), 20)
        self.assertIn("AskUserQuestion", [item["name"] for item in tools])
        ask = dict(AskUserQuestionTool().spec().input_schema)
        tools = [
            *tools,
            {"name": "BrokenAnyOf", "description": "bad", "input_schema": {"anyOf": [ask]}},
        ]

        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _ok_response()
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            response = provider.chat(
                [ChatMessage(role="user", content="hello")],
                tools=tools,
            )
            self.assertIsInstance(response, ChatResponse)
            kwargs = mock_client.messages.create.call_args.kwargs
            sent = kwargs["tools"]
            self.assertGreaterEqual(len(sent), 20)
            names = [item["name"] for item in sent]
            self.assertIn("AskUserQuestion", names)
            for item in sent:
                self.assertEqual(set(item.keys()), {"name", "description", "input_schema"})
                schema = item["input_schema"]
                self.assertEqual(schema.get("type"), "object", item["name"])
                self.assertIn("properties", schema)
                self.assertNotIn("anyOf", schema)
                self.assertNotIn("oneOf", schema)

    def test_schema_type_error_retries_without_tools(self) -> None:
        class Fake400(Exception):
            body = {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "tools.17.custom.input_schema.type: Field required",
                },
            }

        tools = serialize_tools_for_provider(
            build_default_registry(include_user_tools=False),
            include_optional_connectors=False,
        )
        self.assertGreaterEqual(len(tools), 20)

        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [Fake400("Error code: 400"), _ok_response()]
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            response = provider.chat(
                [ChatMessage(role="user", content="hello")],
                tools=tools,
            )
            self.assertEqual(response.content, "ok")
            self.assertEqual(mock_client.messages.create.call_count, 2)
            first = mock_client.messages.create.call_args_list[0].kwargs
            second = mock_client.messages.create.call_args_list[1].kwargs
            self.assertIn("tools", first)
            self.assertNotIn("tools", second)
            self.assertEqual(first["tools"][17]["input_schema"]["type"], "object")

    def test_empty_tools_are_omitted(self) -> None:
        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _ok_response()
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            provider.chat([ChatMessage(role="user", content="hello")], tools=[])
            kwargs = mock_client.messages.create.call_args.kwargs
            self.assertNotIn("tools", kwargs)

    def test_prepare_classic_shape_and_error_detector(self) -> None:
        payload = prepare_anthropic_tools([
            {
                "name": "Skill",
                "description": "x",
                "input_schema": {"anyOf": [{"type": "object", "properties": {"skill": {"type": "string"}}}]},
            }
        ])
        self.assertEqual(payload[0]["input_schema"]["type"], "object")
        self.assertIn("skill", payload[0]["input_schema"]["properties"])
        self.assertNotIn("anyOf", payload[0]["input_schema"])
        exc = Exception("Error code: 400 - tools.17.custom.input_schema.type: Field required")
        self.assertTrue(is_input_schema_type_error(exc))

    def _stream(self, text: str = "ok"):
        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.text_stream = iter([text])
        mock_stream.get_final_message.return_value = _ok_response()
        return mock_stream

    def test_chat_stream_response_retries_without_tools(self) -> None:
        class Stream400(Exception):
            status_code = 400
            body = '{"type":"error","error":{"type":"invalid_request_error","message":"tools.17.custom.input_schema.type: Field required"}}'

        tools = serialize_tools_for_provider(
            build_default_registry(include_user_tools=False),
            include_optional_connectors=False,
        )
        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.stream.side_effect = [Stream400("Error code: 400"), self._stream("streamed ok")]
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            chunks: list[str] = []
            response = provider.chat_stream_response(
                [ChatMessage(role="user", content="hello")],
                tools=tools,
                on_text_chunk=chunks.append,
            )
            self.assertEqual(response.content, "ok")
            self.assertEqual("".join(chunks), "streamed ok")
            self.assertEqual(mock_client.messages.stream.call_count, 2)
            first = mock_client.messages.stream.call_args_list[0].kwargs
            second = mock_client.messages.stream.call_args_list[1].kwargs
            self.assertIn("tools", first)
            self.assertNotIn("tools", second)
            for item in first["tools"]:
                self.assertEqual(set(item.keys()), {"name", "description", "input_schema"})
                self.assertEqual(item["input_schema"].get("type"), "object")

    def test_chat_stream_retries_without_tools(self) -> None:
        class Stream400(Exception):
            status_code = 400
            body = {"error": {"message": "tools.17.custom.input_schema.type: Field required"}}

        tools = [{"name": "Skill", "description": "x", "input_schema": {"anyOf": [{"properties": {}}]}}]
        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.stream.side_effect = [Stream400("Error code: 400"), self._stream("plain")]
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            text = "".join(provider.chat_stream([ChatMessage(role="user", content="hi")], tools=tools))
            self.assertEqual(text, "plain")
            self.assertNotIn("tools", mock_client.messages.stream.call_args_list[1].kwargs)

    def test_dynamic_mcp_tool_is_classic_shape(self) -> None:
        payload = prepare_anthropic_tools([
            {"name": "mcp__fs__read", "description": "dyn", "parameters": {"anyOf": [{"properties": {"uri": {"type": "string"}}}]}},
        ])
        self.assertEqual(payload[0]["name"], "mcp__fs__read")
        self.assertEqual(payload[0]["input_schema"]["type"], "object")
        self.assertIn("uri", payload[0]["input_schema"]["properties"])

    def test_custom_wrapped_tool_is_classic_shape(self) -> None:
        payload = prepare_anthropic_tools([
            {
                "type": "custom",
                "custom": {
                    "name": "Skill",
                    "description": "wrapped",
                    "input_schema": {"anyOf": [{"properties": {"skill": {"type": "string"}}}]},
                },
            }
        ])
        self.assertEqual(payload[0]["name"], "Skill")
        self.assertEqual(set(payload[0].keys()), {"name", "description", "input_schema"})
        self.assertEqual(payload[0]["input_schema"]["type"], "object")
        self.assertIn("skill", payload[0]["input_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
