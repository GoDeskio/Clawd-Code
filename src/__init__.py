"""Clawd Codex - Claude Code Python Implementation."""

from .version import get_version

__version__ = get_version()
__author__ = "Clawd Codex Team"

from .config import load_config, get_provider_config

try:  # pragma: no cover
    from .providers.base import BaseProvider
except Exception:  # pragma: no cover
    BaseProvider = None  # type: ignore[assignment]

__all__ = [
    "__version__",
    "__author__",
    "load_config",
    "get_provider_config",
    "BaseProvider",
]
