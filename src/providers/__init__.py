"""LLM Providers for Clawd Codex."""

from __future__ import annotations

from typing import TypedDict

from .base import BaseProvider, ChatMessage, ChatResponse
from .huggingface_connect import DEFAULT_HF_MODELS, HF_ROUTER


# Provider metadata for login/UI
class ProviderInfo(TypedDict, total=False):
    label: str
    default_base_url: str
    default_model: str
    available_models: list[str]
    requires_key: bool
    kind: str
    token_label: str
    help: str


PROVIDER_INFO: dict[str, ProviderInfo] = {
    "anthropic": {
        "label": "Anthropic Claude",
        "default_base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-6",
        "requires_key": True,
        "kind": "cloud",
        "token_label": "API key",
        "help": "Cloud provider. Key stays in ~/.clawd/config.json.",
        "available_models": [
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
        ],
    },
    "openai": {
        "label": "OpenAI GPT",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5.4",
        "requires_key": True,
        "kind": "cloud",
        "token_label": "API key",
        "help": "Cloud provider. Key stays in ~/.clawd/config.json.",
        "available_models": [
            # GPT-5.4 series (latest flagship)
            "gpt-5.4",
            "gpt-5.4-pro",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            # GPT-5.2 series (previous)
            "gpt-5.2",
            "gpt-5.2-pro",
            "gpt-5.2-mini",
            "gpt-5.2-nano",
            # GPT-5.3-Codex (coding-specialized)
            "gpt-5.3-codex",
            # Legacy GPT-4 series
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
        ],
    },
    "glm": {
        "label": "Zhipu GLM (z.ai)",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "zai/glm-5",
        "requires_key": True,
        "kind": "cloud",
        "token_label": "API key",
        "help": "Cloud provider. Key stays in ~/.clawd/config.json.",
        "available_models": [
            # GLM-5 series (latest, requires zai/ prefix)
            "zai/glm-5",
            "zai/glm-5-turbo",
            # GLM-4 series (standard, zai/ prefix)
            "zai/glm-4",
            "zai/glm-4-plus",
            "zai/glm-4-air",
            "zai/glm-4-flash",
            "zai/glm-4.5",
            "zai/glm-4.6",
            "zai/glm-4.7",
            # GLM-3 series (legacy)
            "zai/glm-3-turbo",
        ],
    },
    "minimax": {
        "label": "Minimax AI",
        "default_base_url": "https://api.minimaxi.com/anthropic",
        "default_model": "MiniMax-M2.7",
        "requires_key": True,
        "kind": "cloud",
        "token_label": "API key",
        "help": "Cloud provider. Key stays in ~/.clawd/config.json.",
        "available_models": [
            # M2 series (latest)
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "M2-her",
            # Historical
            "MiniMax-M2.1",
            "MiniMax-M2.1-highspeed",
            "MiniMax-M2",
        ],
    },
    "huggingface": {
        "label": "Hugging Face",
        "default_base_url": HF_ROUTER,
        "default_model": DEFAULT_HF_MODELS[0],
        "requires_key": True,
        "kind": "huggingface",
        "token_label": "Hugging Face token",
        "help": "Hub + Inference. Create a token at https://huggingface.co/settings/tokens. Test the connection, then pick a Hub model. Token stays on this machine — never in git.",
        "available_models": list(DEFAULT_HF_MODELS),
    },
    "local": {
        "label": "Local LLM",
        "default_base_url": "http://127.0.0.1:11434/v1",
        "default_model": "",
        "requires_key": False,
        "kind": "local",
        "token_label": "Optional API key",
        "help": "Any OpenAI-compatible local server: Ollama (default http://127.0.0.1:11434), LM Studio, vLLM, llama.cpp, Hugging Face TGI, or a custom loopback/LAN URL. Jonathan Ai will not expose it on the WAN.",
        "available_models": [],
    },
}


def get_provider_info(provider_name: str) -> ProviderInfo:
    """Get provider info by name."""
    if provider_name not in PROVIDER_INFO:
        raise ValueError(f"Unknown provider: {provider_name}")
    return PROVIDER_INFO[provider_name]


def get_provider_class(provider_name: str):
    """Get provider class by name."""
    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider
    if provider_name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider
    if provider_name == "glm":
        from .glm_provider import GLMProvider

        return GLMProvider
    if provider_name == "minimax":
        from .minimax_provider import MinimaxProvider

        return MinimaxProvider
    if provider_name == "huggingface":
        from .huggingface_provider import HuggingFaceProvider

        return HuggingFaceProvider
    if provider_name == "local":
        from .local_provider import LocalLLMProvider

        return LocalLLMProvider
    raise ValueError(f"Unknown provider: {provider_name}")


# Legacy registry for display purposes
AVAILABLE_PROVIDERS: dict[str, str] = {k: v["label"] for k, v in PROVIDER_INFO.items()}


__all__ = [
    "BaseProvider",
    "ChatMessage",
    "ChatResponse",
    "get_provider_class",
    "get_provider_info",
    "PROVIDER_INFO",
    "AVAILABLE_PROVIDERS",
]
