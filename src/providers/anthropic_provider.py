"""Anthropic provider implementation."""

from __future__ import annotations

from typing import Generator, Optional, Any

try:
    import anthropic  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    class _MissingAnthropic:
        class Anthropic:  # type: ignore[no-redef]
            def __init__(self, *args, **kwargs):
                raise ModuleNotFoundError(
                    "anthropic package is not installed. Install optional dependencies to use AnthropicProvider."
                )

    anthropic = _MissingAnthropic()

from .base import BaseProvider, ChatResponse, MessageInput, TextChunkCallback
from src.tool_system.schema_sanitize import (
    is_input_schema_type_error,
    log_rejected_tool_index,
    prepare_anthropic_tools,
)


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider."""

    def __init__(
        self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None
    ):
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
            base_url: Base URL (optional)
            model: Default model (default: claude-sonnet-4-6)
        """
        super().__init__(api_key, base_url, model or "claude-sonnet-4-6")

        self._client_kwargs = {"api_key": api_key}
        if base_url:
            self._client_kwargs["base_url"] = base_url
        self.client = None

    def _ensure_client(self):
        if self.client is not None:
            return self.client
        self.client = anthropic.Anthropic(**self._client_kwargs)
        return self.client

    def _classic_tools(self, tools: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return prepare_anthropic_tools(tools)

    def _request_kwargs(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        system: Any,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        safe_extra = {
            key: value
            for key, value in (extra or {}).items()
            if key not in {"tools", "model", "max_tokens", "messages", "system"}
        }
        payload.update(safe_extra)
        return payload

    def _prepare_request(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        system: Any,
        extra: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        prepared = self._classic_tools(tools) if tools else []
        request = self._request_kwargs(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            tools=prepared or None,
            system=system,
            extra=extra,
        )
        return request, prepared

    def _retry_without_tools(self, request: dict[str, Any], prepared: list[dict[str, Any]], exc: BaseException) -> dict[str, Any]:
        log_rejected_tool_index(prepared, exc)
        retry = dict(request)
        retry.pop("tools", None)
        return retry

    def _call_create(
        self,
        client: Any,
        *,
        model: str,
        max_tokens: int,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        system: Any,
        extra: dict[str, Any],
    ) -> Any:
        request, prepared = self._prepare_request(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            tools=tools,
            system=system,
            extra=extra,
        )
        try:
            return client.messages.create(**request)
        except Exception as exc:
            if prepared and is_input_schema_type_error(exc):
                return client.messages.create(**self._retry_without_tools(request, prepared, exc))
            if prepared:
                try:
                    return client.messages.create(**self._retry_without_tools(request, prepared, exc))
                except Exception:
                    raise exc
            raise

    def _stream_request(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        system: Any,
        extra: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return self._prepare_request(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            tools=tools,
            system=system,
            extra=extra,
        )

    def _build_chat_response(self, response: Any) -> ChatResponse:
        """Convert Anthropic SDK response into the shared ChatResponse shape."""
        content_text = ""
        tool_uses: list[dict[str, Any]] = []

        for block in response.content:
            block_type = getattr(block, "type", "text")
            if block_type == "text":
                text_val = getattr(block, "text", "")
                if text_val is not None:
                    content_text += str(text_val)
            elif block_type == "tool_use":
                tool_uses.append({
                    "id": str(getattr(block, "id", "")),
                    "name": str(getattr(block, "name", "")),
                    "input": dict(getattr(block, "input", {})),
                })

        usage = getattr(response, "usage", None)
        return ChatResponse(
            content=content_text,
            model=getattr(response, "model", self.model or ""),
            usage={
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            },
            finish_reason=str(getattr(response, "stop_reason", "stop")),
            tool_uses=tool_uses if tool_uses else None,
        )

    def chat(
        self,
        messages: list[MessageInput],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs
    ) -> ChatResponse:
        """Synchronous chat completion.

        Args:
            messages: List of chat messages
            tools: Optional list of tool schemas
            **kwargs: Additional parameters (model, max_tokens, temperature, etc.)

        Returns:
            Chat response
        """
        model = self._get_model(**kwargs)
        max_tokens = kwargs.get("max_tokens", 4096)

        system = kwargs.pop("system", None)

        # Convert messages to Anthropic format
        anthropic_messages = self._prepare_messages(messages)

        client = self._ensure_client()
        extra = {k: v for k, v in kwargs.items() if k not in ["model", "max_tokens", "tools"]}
        response = self._call_create(
            client,
            model=model,
            max_tokens=max_tokens,
            messages=anthropic_messages,
            tools=tools,
            system=system,
            extra=extra,
        )
        return self._build_chat_response(response)

    def chat_stream(
        self,
        messages: list[MessageInput],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """Streaming chat completion.

        Args:
            messages: List of chat messages
            tools: Optional list of tool schemas
            **kwargs: Additional parameters

        Yields:
            Chunks of response content
        """
        model = self._get_model(**kwargs)
        max_tokens = kwargs.get("max_tokens", 4096)

        anthropic_messages = self._prepare_messages(messages)
        client = self._ensure_client()
        extra = {k: v for k, v in kwargs.items() if k not in ["model", "max_tokens", "tools"]}
        request, prepared = self._stream_request(
            model=model,
            max_tokens=max_tokens,
            messages=anthropic_messages,
            tools=tools,
            system=None,
            extra=extra,
        )
        yielded = False
        active = request
        try:
            with client.messages.stream(**active) as stream:
                for text in stream.text_stream:
                    yielded = True
                    yield text
            return
        except Exception as exc:
            if yielded:
                raise
            if not prepared:
                raise
            if not is_input_schema_type_error(exc):
                # Prefer a no-tools answer over failing the first streamed message.
                pass
            active = self._retry_without_tools(request, prepared, exc)
        with client.messages.stream(**active) as stream:
            for text in stream.text_stream:
                yield text

    def chat_stream_response(
        self,
        messages: list[MessageInput],
        tools: Optional[list[dict[str, Any]]] = None,
        on_text_chunk: TextChunkCallback | None = None,
        **kwargs
    ) -> ChatResponse:
        """Stream Anthropic text chunks and return the final structured response."""
        model = self._get_model(**kwargs)
        max_tokens = kwargs.get("max_tokens", 4096)
        system = kwargs.pop("system", None)
        anthropic_messages = self._prepare_messages(messages)

        client = self._ensure_client()
        extra = {k: v for k, v in kwargs.items() if k not in ["model", "max_tokens", "tools"]}
        request, prepared = self._stream_request(
            model=model,
            max_tokens=max_tokens,
            messages=anthropic_messages,
            tools=tools,
            system=system,
            extra=extra,
        )
        streamed_text = ""
        final_message = None

        def _read_stream(req: dict[str, Any]) -> tuple[str, Any]:
            text_out = ""
            final = None
            with client.messages.stream(**req) as stream:
                for text in stream.text_stream:
                    if not text:
                        continue
                    text_out += text
                    if on_text_chunk is not None:
                        on_text_chunk(text)
                try:
                    final = stream.get_final_message()
                except Exception as final_exc:
                    if is_input_schema_type_error(final_exc):
                        raise
                    final = None
            return text_out, final

        try:
            streamed_text, final_message = _read_stream(request)
        except Exception as exc:
            if not prepared:
                raise
            retry = self._retry_without_tools(request, prepared, exc)
            streamed_text, final_message = _read_stream(retry)

        if final_message is not None:
            return self._build_chat_response(final_message)

        return ChatResponse(
            content=streamed_text,
            model=model,
            usage={},
            finish_reason="stop",
            tool_uses=None,
        )

    def get_available_models(self) -> list[str]:
        """Get list of available Anthropic models.

        Returns:
            List of model names
        """
        return [
            # Claude 4 series (latest)
            "claude-sonnet-4-6",
            "claude-sonnet-4-5",
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-0",
            "claude-sonnet-4-20250514",
            "claude-opus-4-6",
            "claude-opus-4-5",
            "claude-opus-4-5-20251101",
            "claude-opus-4-1",
            "claude-opus-4-1-20250805",
            "claude-opus-4-0",
            "claude-opus-4-20250514",
            "claude-haiku-4-5",
            "claude-haiku-4-5-20251001",
            # Legacy
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]
