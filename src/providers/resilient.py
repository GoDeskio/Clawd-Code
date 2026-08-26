"""Small in-process provider resilience layer.

OmniRoute was reviewed as a design reference.  Jonathan keeps its own provider
classes and does not run a proxy or silently move prompts between providers.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Generator, Optional

from .base import BaseProvider, ChatResponse, MessageInput, TextChunkCallback


def _status_code(exc: BaseException) -> int | None:
    for source in (exc, getattr(exc, "response", None)):
        value = getattr(source, "status_code", None) or getattr(source, "status", None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            pass
    return None


def is_transient_provider_error(exc: BaseException) -> bool:
    """Retry only transport, throttling and server failures—not auth or 400s."""
    code = _status_code(exc)
    if code is not None:
        return code in {408, 409, 425, 429} or 500 <= code <= 599
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    markers = ("timeout", "timed out", "connection reset", "connection aborted", "temporarily unavailable")
    return any(marker in name or marker in text for marker in markers)


class ResilientProvider(BaseProvider):
    """Retry transient failures and open a short circuit after repeated faults."""

    def __init__(self, provider: BaseProvider, *, retries: int = 1, failure_threshold: int = 3, cooldown: float = 30.0) -> None:
        super().__init__(provider.api_key, provider.base_url, provider.model)
        self.provider = provider
        self.protocol_family = "anthropic" if provider.__class__.__name__ in {"AnthropicProvider", "MinimaxProvider"} else "openai"
        self.retries = max(0, int(retries))
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown = max(0.0, float(cooldown))
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    def health(self) -> dict[str, Any]:
        with self._lock:
            remaining = max(0.0, self.cooldown - (time.monotonic() - self._opened_at)) if self._opened_at else 0.0
            return {"state": "open" if remaining > 0 else "closed", "consecutive_failures": self._failures, "retry_after_seconds": round(remaining, 2)}

    def _before_call(self) -> None:
        with self._lock:
            if self._opened_at and time.monotonic() - self._opened_at < self.cooldown:
                remaining = self.cooldown - (time.monotonic() - self._opened_at)
                raise RuntimeError(f"Provider circuit is cooling down; retry in {remaining:.1f}s")
            if self._opened_at:
                self._opened_at = 0.0
                self._failures = 0

    def _success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0

    def _failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self._before_call()
        for attempt in range(self.retries + 1):
            try:
                result = getattr(self.provider, method)(*args, **kwargs)
                self._success()
                return result
            except Exception as exc:
                self._failure()
                if attempt >= self.retries or not is_transient_provider_error(exc):
                    raise
                time.sleep(min(0.2 * (2**attempt), 1.0))
        raise RuntimeError("unreachable")

    def chat(self, messages: list[MessageInput], tools: Optional[list[dict[str, Any]]] = None, **kwargs: Any) -> ChatResponse:
        return self._call("chat", messages, tools=tools, **kwargs)

    def chat_stream(self, messages: list[MessageInput], tools: Optional[list[dict[str, Any]]] = None, **kwargs: Any) -> Generator[str, None, None]:
        self._before_call()
        emitted = False
        for attempt in range(self.retries + 1):
            try:
                for chunk in self.provider.chat_stream(messages, tools=tools, **kwargs):
                    emitted = True
                    yield chunk
                self._success()
                return
            except Exception as exc:
                self._failure()
                if emitted or attempt >= self.retries or not is_transient_provider_error(exc):
                    raise
                time.sleep(min(0.2 * (2**attempt), 1.0))

    def chat_stream_response(self, messages: list[MessageInput], tools: Optional[list[dict[str, Any]]] = None, on_text_chunk: TextChunkCallback | None = None, **kwargs: Any) -> ChatResponse:
        emitted = False
        def observed(chunk: str) -> None:
            nonlocal emitted
            emitted = emitted or bool(chunk)
            if on_text_chunk is not None:
                on_text_chunk(chunk)
        self._before_call()
        for attempt in range(self.retries + 1):
            try:
                response = self.provider.chat_stream_response(messages, tools=tools, on_text_chunk=observed, **kwargs)
                self._success()
                return response
            except Exception as exc:
                self._failure()
                if emitted or attempt >= self.retries or not is_transient_provider_error(exc):
                    raise
                time.sleep(min(0.2 * (2**attempt), 1.0))
        raise RuntimeError("unreachable")

    def get_available_models(self) -> list[str]:
        return self.provider.get_available_models()


def resilient(provider: BaseProvider) -> ResilientProvider:
    return provider if isinstance(provider, ResilientProvider) else ResilientProvider(provider)
