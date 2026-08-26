from __future__ import annotations

import unittest
from unittest.mock import patch

from src.tool_system.defaults import build_default_registry
from src.tool_system.tools.speech_studio import SpeechStudioTool, speech_status


class SpeechStudioTests(unittest.TestCase):
    def test_status_is_local_and_registered(self) -> None:
        status = speech_status()
        self.assertEqual(status["privacy"], "audio remains local")
        self.assertIsNotNone(build_default_registry(include_user_tools=False).get("SpeechStudio"))

    def test_schema_supports_transcription_and_synthesis(self) -> None:
        spec = SpeechStudioTool().spec()
        self.assertEqual(spec.input_schema["type"], "object")
        self.assertEqual(spec.input_schema["additionalProperties"], False)
        self.assertEqual(spec.input_schema["properties"]["action"]["enum"], ["status", "transcribe", "synthesize"])

    @patch("src.tool_system.tools.speech_studio.importlib.util.find_spec", return_value=None)
    def test_status_does_not_download_a_model(self, _find_spec) -> None:
        self.assertFalse(speech_status()["transcription_ready"])
