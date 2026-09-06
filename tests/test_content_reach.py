from __future__ import annotations

import unittest

from src.tool_system.defaults import build_default_registry
from src.tool_system.tools.content_reach import ContentReachTool, _public_url
from src.tool_system.tools.web_fetch import _html_to_text


class ContentReachTests(unittest.TestCase):
    def test_registered_with_strict_schema(self) -> None:
        tool = build_default_registry(include_user_tools=False).get("ContentReach")
        self.assertIsNotNone(tool)
        self.assertFalse(ContentReachTool().spec().input_schema["additionalProperties"])

    def test_private_urls_are_rejected(self) -> None:
        with self.assertRaises(Exception):
            _public_url("http://127.0.0.1/private")

    def test_visible_html_excludes_scripts_styles_and_hidden_text(self) -> None:
        source = "<html><head><title>secret</title></head><body><h1>Hello</h1><script>ignore()</script><p hidden>hidden</p><p>World</p></body></html>"
        result = _html_to_text(source)
        self.assertEqual(result, "Hello World")
