"""OpenAI-compatible local / self-hosted LLM provider."""

from __future__ import annotations

from typing import Any, Optional

try:
    from openai import OpenAI  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    OpenAI = None

from .local_endpoints import list_local_models, normalize_openai_base
from .openai_compatible import OpenAICompatibleProvider


class LocalLLMProvider(OpenAICompatibleProvider):
    """Talk to Ollama, LM Studio, vLLM, llama.cpp, TGI, or a custom local URL."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        url = normalize_openai_base(base_url or "http://127.0.0.1:11434/v1")
        super().__init__(api_key or "local", url, model or "")

    def _create_client(self) -> Any:
        if OpenAI is None:  # pragma: no cover
            raise ModuleNotFoundError(
                "openai package is not installed. Install it to use LocalLLMProvider."
            )
        return OpenAI(api_key=self.api_key or "local", base_url=self.base_url)

    def get_available_models(self) -> list[str]:
        try:
            return list_local_models(self.base_url or "http://127.0.0.1:11434/v1", self.api_key)
        except Exception:
            return []
