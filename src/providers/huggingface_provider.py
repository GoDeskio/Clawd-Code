"""Hugging Face Inference provider (OpenAI-compatible router)."""

from __future__ import annotations

from typing import Any, Optional

try:
    from openai import OpenAI  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    OpenAI = None

from .huggingface_connect import DEFAULT_HF_MODELS, HF_ROUTER
from .openai_compatible import OpenAICompatibleProvider


class HuggingFaceProvider(OpenAICompatibleProvider):
    """Chat via Hugging Face Inference (router.huggingface.co/v1)."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            api_key,
            base_url or HF_ROUTER,
            model or DEFAULT_HF_MODELS[0],
        )

    def _create_client(self) -> Any:
        if OpenAI is None:  # pragma: no cover
            raise ModuleNotFoundError(
                "openai package is not installed. Install it to use HuggingFaceProvider."
            )
        if not (self.api_key or "").strip():
            raise ValueError("Hugging Face token is required")
        return OpenAI(api_key=self.api_key, base_url=self.base_url or HF_ROUTER)

    def get_available_models(self) -> list[str]:
        return list(DEFAULT_HF_MODELS)
