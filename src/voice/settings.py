"""Per-user voice settings stored on this machine.

Audio stays local unless the saved speech-to-text or text-to-speech provider
is OpenAI or xAI. Keys saved here never appear in the public settings view.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import VoiceError

LOCAL = "local"
OPENAI = "openai"
XAI = "xai"
PROVIDERS = (LOCAL, OPENAI, XAI)

DEFAULT_SETTINGS: dict[str, Any] = {
    "stt_provider": LOCAL,
    "tts_provider": LOCAL,
    "input_device": "",
    "output_device": "",
    "push_to_talk": True,
    "wake_word_enabled": False,
    "wake_word": "jonathan",
    "language": "en",
    "stt_model": "faster-whisper-tiny",
    "tts_voice": "en_US-lessac-medium",
    "cloud_voice": "alloy",
    "openai_api_key": "",
    "xai_api_key": "",
}

_SECRET_KEYS = frozenset({"openai_api_key", "xai_api_key"})


def voice_dir() -> Path:
    override = os.environ.get("JONATHAN_VOICE_DIR", "").strip()
    path = Path(override) if override else Path.home() / ".clawd" / "voice"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_id() -> str:
    from ..agent.memory import current_user_id

    return current_user_id()


def settings_path(directory: Path | None = None) -> Path:
    root = directory or voice_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"settings-{_user_id()}.json"


def models_dir(directory: Path | None = None) -> Path:
    root = directory or voice_dir()
    path = root / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if os.name == "nt":
        path.write_text(text, encoding="utf-8")
        return
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def load_settings(directory: Path | None = None) -> dict[str, Any]:
    path = settings_path(directory)
    stored: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            stored = loaded
    merged = dict(DEFAULT_SETTINGS)
    merged.update({key: stored[key] for key in DEFAULT_SETTINGS if key in stored})
    return merged


def audio_stays_local(settings: dict[str, Any]) -> bool:
    return settings.get("stt_provider") == LOCAL and settings.get("tts_provider") == LOCAL


def public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Settings safe to show in the UI and command output."""
    view = {key: settings.get(key) for key in DEFAULT_SETTINGS if key not in _SECRET_KEYS}
    view["audio_stays_local"] = audio_stays_local(settings)
    view["openai_key_configured"] = bool(
        str(settings.get("openai_api_key") or "").strip() or os.environ.get("OPENAI_API_KEY")
    )
    view["xai_key_configured"] = bool(str(settings.get("xai_api_key") or "").strip() or os.environ.get("XAI_API_KEY"))
    view["note"] = (
        "Audio stays on this machine."
        if view["audio_stays_local"]
        else "Audio is sent only because a cloud provider is selected."
    )
    return view


def _saved_openai_key() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    try:
        from ..config import get_provider_config

        return str(get_provider_config("openai").get("api_key") or "")
    except Exception:
        return ""


def _coerce_provider(value: Any, label: str) -> str:
    name = str(value or "").strip().lower()
    if name not in PROVIDERS:
        raise VoiceError(f"{label} must be local, openai, or xai.")
    return name


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise VoiceError(f"Expected on or off, got {value!r}.")


def _coerce_phrase(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > 64 or any(ord(char) > 127 for char in text):
        raise VoiceError("Wake word must be 1 to 64 plain characters.")
    return text


def _coerce_language(value: Any) -> str:
    text = str(value or "").strip()
    parts = text.split("-")
    if not text or len(parts) > 2 or any(not part.isalpha() or len(part) > 8 for part in parts):
        raise VoiceError("Language must look like en or en-US.")
    return text


def _coerce(key: str, value: Any) -> Any:
    if key in {"stt_provider", "tts_provider"}:
        return _coerce_provider(value, "Speech provider" if key == "stt_provider" else "Voice provider")
    if key in {"push_to_talk", "wake_word_enabled"}:
        return _coerce_bool(value)
    if key == "wake_word":
        return _coerce_phrase(value)
    if key == "language":
        return _coerce_language(value)
    if key in _SECRET_KEYS:
        return str(value or "")
    if key in {"input_device", "output_device", "stt_model", "tts_voice", "cloud_voice"}:
        return str(value or "").strip()
    raise VoiceError(f"Unknown voice setting {key}.")


def update_settings(changes: dict[str, Any], directory: Path | None = None) -> dict[str, Any]:
    current = load_settings(directory)
    for key, value in changes.items():
        if key not in DEFAULT_SETTINGS:
            raise VoiceError(f"Unknown voice setting {key}.")
        if key in _SECRET_KEYS and not str(value or "").strip():
            continue
        current[key] = _coerce(key, value)
    _write_private(settings_path(directory), current)
    return public_settings(current)


def cloud_api_key(provider: str, settings: dict[str, Any]) -> str:
    if provider == OPENAI:
        saved = str(settings.get("openai_api_key") or "").strip()
        return saved or _saved_openai_key()
    if provider == XAI:
        return str(settings.get("xai_api_key") or "").strip() or os.environ.get("XAI_API_KEY", "")
    return ""
