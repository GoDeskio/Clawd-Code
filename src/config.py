"""Configuration management for Clawd Codex."""

from __future__ import annotations

import json
import base64
import os
from pathlib import Path
from typing import Any, Optional


def get_config_path() -> Path:
    """Get the path to the configuration file."""
    config_dir = Path.home() / ".clawd"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def _provider_slot(name: str, info: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_key": "",
        "base_url": info["default_base_url"],
        "default_model": info["default_model"],
    }


def _ensure_provider_slots(config: dict[str, Any]) -> dict[str, Any]:
    from src.providers import PROVIDER_INFO

    providers = config.setdefault("providers", {})
    for name, info in PROVIDER_INFO.items():
        if name not in providers or not isinstance(providers.get(name), dict):
            providers[name] = _provider_slot(name, info)
        else:
            providers[name].setdefault("base_url", info["default_base_url"])
            providers[name].setdefault("default_model", info["default_model"])
            providers[name].setdefault("api_key", "")
    return config


def _get_default_config_from_providers() -> dict[str, Any]:
    """Build default config using provider info registry."""
    from src.providers import PROVIDER_INFO

    return _ensure_provider_slots({
        "default_provider": "anthropic",
        "providers": {
            name: _provider_slot(name, info)
            for name, info in PROVIDER_INFO.items()
        },
        "session": {
            "auto_save": True,
            "max_history": 100
        }
    })


def get_default_config() -> dict[str, Any]:
    """Generate default configuration."""
    return _get_default_config_from_providers()


def _encode_api_key(api_key: str) -> str:
    """Encode API key for basic obfuscation."""
    return base64.b64encode(api_key.encode()).decode()


def _decode_api_key(encoded_key: str) -> str:
    """Decode API key."""
    try:
        return base64.b64decode(encoded_key.encode()).decode()
    except Exception:
        # If decoding fails, return as-is (might be plain text)
        return encoded_key


def load_config() -> dict[str, Any]:
    """Load configuration from file.

    Returns:
        Configuration dictionary
    """
    config_path = get_config_path()

    if not config_path.exists():
        # Create default config
        config = get_default_config()
        save_config(config)
        return config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Decode API keys
        for provider_name, provider_config in config.get("providers", {}).items():
            if provider_config.get("api_key"):
                provider_config["api_key"] = _decode_api_key(provider_config["api_key"])

        return _ensure_provider_slots(config)
    except Exception as e:
        print(f"Error loading config: {e}")
        return get_default_config()


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file.

    Args:
        config: Configuration dictionary to save
    """
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a copy to avoid modifying the original
    config_copy = json.loads(json.dumps(config))

    # Encode API keys
    for provider_name, provider_config in config_copy.get("providers", {}).items():
        if provider_config.get("api_key"):
            provider_config["api_key"] = _encode_api_key(provider_config["api_key"])

    if os.name == "nt":
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_copy, f, indent=2, ensure_ascii=False)
    else:
        fd = os.open(
            config_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config_copy, f, indent=2, ensure_ascii=False)
        os.chmod(config_path, 0o600)


def get_provider_config(provider: str) -> dict[str, Any]:
    """Get configuration for a specific provider.

    Args:
        provider: Provider name (anthropic, openai, glm, minimax)

    Returns:
        Provider configuration dictionary
    """
    config = load_config()
    providers = config.get("providers", {})

    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}")

    return providers[provider]


def set_api_key(provider: str, api_key: str, base_url: Optional[str] = None,
                default_model: Optional[str] = None) -> None:
    """Set API key for a provider.

    Args:
        provider: Provider name (anthropic, openai, glm, minimax)
        api_key: API key to set
        base_url: Optional base URL override
        default_model: Optional default model override
    """
    config = load_config()

    if provider not in config.get("providers", {}):
        # Add new provider if it doesn't exist
        if "providers" not in config:
            config["providers"] = {}
        config["providers"][provider] = {}

    config["providers"][provider]["api_key"] = api_key

    if base_url is not None:
        config["providers"][provider]["base_url"] = base_url

    if default_model is not None:
        config["providers"][provider]["default_model"] = default_model

    save_config(config)


def set_default_provider(provider: str) -> None:
    """Set the default provider.

    Args:
        provider: Provider name
    """
    config = load_config()
    config["default_provider"] = provider
    save_config(config)


def get_default_provider() -> str:
    """Get the default provider.

    Returns:
        Default provider name
    """
    config = load_config()
    return config.get("default_provider", "anthropic")


def provider_requires_key(provider: str) -> bool:
    from src.providers import PROVIDER_INFO

    info = PROVIDER_INFO.get(provider) or {}
    return bool(info.get("requires_key", True))


def is_provider_ready(provider: str, provider_config: dict[str, Any] | None = None) -> bool:
    """A cloud/HF provider is ready with a key; local is ready after a model is chosen."""
    cfg = provider_config if provider_config is not None else get_provider_config(provider)
    if not isinstance(cfg, dict):
        return False
    if provider_requires_key(provider):
        return bool(str(cfg.get("api_key") or "").strip())
    return bool(str(cfg.get("base_url") or "").strip() and str(cfg.get("default_model") or "").strip())


def has_configured_provider() -> bool:
    """Return True if at least one provider is ready to chat."""
    config = load_config()
    for name, provider_config in config.get("providers", {}).items():
        if isinstance(provider_config, dict) and is_provider_ready(name, provider_config):
            return True
    return False


def public_config() -> dict[str, Any]:
    """Return configuration safe to send to a desktop UI (keys masked)."""
    config = load_config()
    providers: dict[str, Any] = {}
    for name, provider_config in config.get("providers", {}).items():
        if not isinstance(provider_config, dict):
            continue
        api_key = str(provider_config.get("api_key") or "")
        if not api_key:
            masked = ""
        elif len(api_key) > 12:
            masked = f"{api_key[:4]}…{api_key[-4:]}"
        else:
            masked = "••••"
        providers[name] = {
            "configured": is_provider_ready(name, provider_config),
            "requires_key": provider_requires_key(name),
            "api_key_masked": masked,
            "base_url": provider_config.get("base_url", ""),
            "default_model": provider_config.get("default_model", ""),
        }
    desktop = config.get("desktop") if isinstance(config.get("desktop"), dict) else {}
    return {
        "default_provider": config.get("default_provider", "anthropic"),
        "providers": providers,
        "configured": has_configured_provider(),
        "desktop": {
            "workspace": desktop.get("workspace", ""),
            "notify_on_complete": bool(desktop.get("notify_on_complete", True)),
        },
    }


def get_desktop_settings() -> dict[str, Any]:
    config = load_config()
    desktop = config.get("desktop")
    if not isinstance(desktop, dict):
        desktop = {}
    return {
        "workspace": desktop.get("workspace", ""),
        "notify_on_complete": bool(desktop.get("notify_on_complete", True)),
    }


def update_desktop_settings(*, workspace: Optional[str] = None, notify_on_complete: Optional[bool] = None) -> dict[str, Any]:
    config = load_config()
    desktop = config.get("desktop")
    if not isinstance(desktop, dict):
        desktop = {}
    if workspace is not None:
        desktop["workspace"] = workspace
    if notify_on_complete is not None:
        desktop["notify_on_complete"] = bool(notify_on_complete)
    config["desktop"] = desktop
    save_config(config)
    return get_desktop_settings()
