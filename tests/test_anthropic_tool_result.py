"""Anthropic tool_result.content must be a string or list of content blocks."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from src.agent.conversation import (
    Conversation,
    normalize_tool_result_content,
    sanitize_legacy_binary_upload_text,
    sanitize_anthropic_messages,
)
from src.providers.anthropic_provider import AnthropicProvider
from src.providers.base import ChatResponse

from tests.test_anthropic_tool_payload import _ok_response


class TestNormalizeToolResultContent(unittest.TestCase):
    def test_legacy_binary_upload_is_hidden_from_context_and_transcript(self) -> None:
        raw = "Please inspect this.\n\n[clipboard attachment: photo.jpg]\n```\n��JFIF\x00" + ("�" * 20) + "\n```"
        cleaned = sanitize_legacy_binary_upload_text(raw)
        self.assertIn("photo.jpg", cleaned)
        self.assertIn("Please inspect this.", cleaned)
        self.assertIn("legacy binary-upload bug", cleaned)
        self.assertNotIn("JFIF", cleaned)
        conversation = Conversation()
        conversation.add_user_message(raw)
        self.assertEqual(conversation.get_messages()[0]["content"], cleaned)

    def test_dict_tool_result_becomes_string(self) -> None:
        payload = {"filePath": "/tmp/a.txt", "type": "text", "content": "hello"}
        normalized = normalize_tool_result_content(payload)
        self.assertIsInstance(normalized, str)
        self.assertEqual(json.loads(normalized), payload)

    def test_string_is_unchanged(self) -> None:
        self.assertEqual(normalize_tool_result_content("already text"), "already text")

    def test_content_block_list_is_kept(self) -> None:
        blocks = [{"type": "text", "text": "ok"}]
        self.assertEqual(normalize_tool_result_content(blocks), blocks)

    def test_plain_list_is_json(self) -> None:
        items = [{"filePath": "a"}, {"filePath": "b"}]
        normalized = normalize_tool_result_content(items)
        self.assertIsInstance(normalized, str)
        self.assertEqual(json.loads(normalized), items)


class TestConversationToolResult(unittest.TestCase):
    def test_add_tool_result_stringifies_dict(self) -> None:
        conv = Conversation()
        payload = {"filePath": "notes.md", "type": "text"}
        conv.add_tool_result_message("toolu_1", payload)
        messages = conv.get_messages()
        content = messages[0]["content"][0]["content"]
        self.assertIsInstance(content, str)
        self.assertEqual(json.loads(content), payload)

    def test_resumed_session_object_tool_result_becomes_string(self) -> None:
        stored = {
            "max_history": 100,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_old",
                            "content": {"filePath": "resume.txt", "type": "text"},
                            "is_error": False,
                        }
                    ],
                    "timestamp": "",
                }
            ],
        }
        conv = Conversation.from_dict(stored)
        content = conv.get_messages()[0]["content"][0]["content"]
        self.assertIsInstance(content, str)
        self.assertEqual(json.loads(content)["filePath"], "resume.txt")


class TestAnthropicPrepareMessages(unittest.TestCase):
    def _history_with_dict_tool_result(self) -> list[dict]:
        return [
            {"role": "user", "content": "read notes"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_4", "name": "Read", "input": {"path": "notes.md"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_4",
                        "content": {"filePath": "notes.md", "type": "text", "content": "hi"},
                    }
                ],
            },
            {"role": "user", "content": "ok continue"},
        ]

    def _assert_tool_result_is_string(self, messages: list) -> None:
        block = messages[2]["content"][0]
        self.assertEqual(block["type"], "tool_result")
        self.assertIsInstance(block["content"], str)
        self.assertEqual(json.loads(block["content"])["filePath"], "notes.md")

    def test_prepare_messages_stringifies_dict_tool_result(self) -> None:
        prepared = sanitize_anthropic_messages(self._history_with_dict_tool_result())
        self._assert_tool_result_is_string(prepared)

    def test_chat_sends_string_tool_result(self) -> None:
        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _ok_response()
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            response = provider.chat(self._history_with_dict_tool_result())
            self.assertIsInstance(response, ChatResponse)
            kwargs = mock_client.messages.create.call_args.kwargs
            self._assert_tool_result_is_string(kwargs["messages"])

    def test_chat_stream_sends_string_tool_result(self) -> None:
        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.text_stream = iter(["ok"])
        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            text = "".join(provider.chat_stream(self._history_with_dict_tool_result()))
            self.assertEqual(text, "ok")
            kwargs = mock_client.messages.stream.call_args.kwargs
            self._assert_tool_result_is_string(kwargs["messages"])

    def test_chat_stream_response_sends_string_tool_result(self) -> None:
        mock_stream = MagicMock()
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = False
        mock_stream.text_stream = iter(["ok"])
        mock_stream.get_final_message.return_value = _ok_response()
        with patch("src.providers.anthropic_provider.anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="test_key")
            response = provider.chat_stream_response(self._history_with_dict_tool_result())
            self.assertEqual(response.content, "ok")
            kwargs = mock_client.messages.stream.call_args.kwargs
            self._assert_tool_result_is_string(kwargs["messages"])


if __name__ == "__main__":
    unittest.main()
