from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.providers.base import ChatResponse
from src.providers.resilient import ResilientProvider, is_transient_provider_error


class StatusError(RuntimeError):
    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {code}")
        self.status_code = code


class ProviderResilienceTests(unittest.TestCase):
    def _provider(self) -> MagicMock:
        provider = MagicMock()
        provider.api_key = "x"
        provider.base_url = "https://example.invalid"
        provider.model = "test-model"
        return provider

    def test_retries_transient_failure_then_recovers(self) -> None:
        provider = self._provider()
        expected = ChatResponse("ok", "test-model", {}, "stop")
        provider.chat.side_effect = [StatusError(503), expected]
        wrapped = ResilientProvider(provider)
        with patch("src.providers.resilient.time.sleep"):
            self.assertIs(wrapped.chat([]), expected)
        self.assertEqual(provider.chat.call_count, 2)
        self.assertEqual(wrapped.health()["state"], "closed")

    def test_never_retries_auth_or_bad_request(self) -> None:
        for code in (400, 401, 403):
            provider = self._provider()
            provider.chat.side_effect = StatusError(code)
            with self.assertRaises(StatusError):
                ResilientProvider(provider).chat([])
            self.assertEqual(provider.chat.call_count, 1)

    def test_stream_does_not_replay_after_visible_output(self) -> None:
        provider = self._provider()
        def broken(*_args, **_kwargs):
            yield "visible"
            raise StatusError(503)
        provider.chat_stream.side_effect = broken
        wrapped = ResilientProvider(provider)
        stream = wrapped.chat_stream([])
        self.assertEqual(next(stream), "visible")
        with self.assertRaises(StatusError):
            next(stream)
        self.assertEqual(provider.chat_stream.call_count, 1)

    def test_classifier(self) -> None:
        self.assertTrue(is_transient_provider_error(StatusError(429)))
        self.assertTrue(is_transient_provider_error(TimeoutError()))
        self.assertFalse(is_transient_provider_error(StatusError(401)))
