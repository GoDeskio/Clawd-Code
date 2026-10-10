"""Per-user knowledge settings. The public view never includes the API key."""

from __future__ import annotations

import json
from pathlib import Path

from src.knowledge.models import DEFAULT_MODEL_ID
from src.knowledge.embed import DEFAULT_CLOUD_MODEL

LOCAL_BACKEND = "local"
CLOUD_BACKEND = "openai"
_BACKENDS = {LOCAL_BACKEND, CLOUD_BACKEND}


def default_settings() -> dict[str, str]:
    return {
        "embedding_backend": LOCAL_BACKEND,
        "model_id": DEFAULT_MODEL_ID,
        "cloud_model": DEFAULT_CLOUD_MODEL,
        "openai_api_key": "",
    }


def load_settings(path: Path) -> dict[str, str]:
    settings = default_settings()
    if not path.is_file():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if not isinstance(raw, dict):
        return settings
    backend = str(raw.get("embedding_backend") or LOCAL_BACKEND).strip().lower()
    if backend in _BACKENDS:
        settings["embedding_backend"] = backend
    model_id = str(raw.get("model_id") or "").strip()
    if model_id:
        settings["model_id"] = model_id
    cloud_model = str(raw.get("cloud_model") or "").strip()
    if cloud_model:
        settings["cloud_model"] = cloud_model
    key = raw.get("openai_api_key")
    if isinstance(key, str):
        settings["openai_api_key"] = key
    return settings


def save_settings(path: Path, settings: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        return


def update_settings(path: Path, changes: dict[str, object]) -> dict[str, str]:
    settings = load_settings(path)
    if "embedding_backend" in changes and changes["embedding_backend"] is not None:
        backend = str(changes["embedding_backend"]).strip().lower()
        if backend not in _BACKENDS:
            raise ValueError("embedding backend must be local or openai")
        settings["embedding_backend"] = backend
    if "model_id" in changes and changes["model_id"] is not None:
        model_id = str(changes["model_id"]).strip()
        if model_id:
            settings["model_id"] = model_id
    if "cloud_model" in changes and changes["cloud_model"] is not None:
        cloud_model = str(changes["cloud_model"]).strip()
        if cloud_model:
            settings["cloud_model"] = cloud_model
    if "openai_api_key" in changes and changes["openai_api_key"] is not None:
        key = str(changes["openai_api_key"])
        if key.strip():
            settings["openai_api_key"] = key.strip()
    save_settings(path, settings)
    return settings


def public_view(settings: dict[str, str], *, document_count: int, model_ready: bool) -> dict[str, object]:
    backend = settings.get("embedding_backend", LOCAL_BACKEND)
    return {
        "embedding_backend": backend,
        "model_id": settings.get("model_id", DEFAULT_MODEL_ID),
        "cloud_model": settings.get("cloud_model", DEFAULT_CLOUD_MODEL),
        "documents_stay_local": backend != CLOUD_BACKEND,
        "cloud_key_configured": bool(settings.get("openai_api_key")),
        "model_ready": model_ready,
        "document_count": document_count,
    }
