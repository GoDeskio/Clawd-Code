"""Hugging Face Hub + Inference helpers.

These functions talk to huggingface.co / router.huggingface.co only when the
user chose the Hugging Face provider or explicitly asked to test, list, or
download a model. Tokens stay on this machine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


HF_ROUTER = "https://router.huggingface.co/v1"
HF_WHOAMI = "https://huggingface.co/api/whoami-v2"
HF_MODELS = "https://huggingface.co/api/models"
HF_CACHE_DIRNAME = "hf-cache"

DEFAULT_HF_MODELS = [
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "google/gemma-2-9b-it",
    "HuggingFaceH4/zephyr-7b-beta",
]


def hf_cache_root(home: Path | None = None) -> Path:
    root = Path(home) if home is not None else Path.home()
    return root / ".clawd" / HF_CACHE_DIRNAME


def _request_json(
    url: str,
    *,
    token: str,
    timeout: float = 12.0,
    method: str = "GET",
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "JonathanAi/0.1 (GoDeskio/Clawd-Code)",
    }
    key = (token or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = Request(url, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        status = int(exc.code)
    except URLError as exc:
        raise ConnectionError(str(exc.reason or exc)) from exc
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", errors="replace")


def verify_huggingface_token(token: str) -> dict[str, Any]:
    """Call whoami. User-initiated only — used by Test connection."""
    key = (token or "").strip()
    if not key:
        raise ValueError("Hugging Face token is required")
    status, payload = _request_json(HF_WHOAMI, token=key)
    if status == 401:
        raise ValueError("Hugging Face token was rejected (401). Create one at https://huggingface.co/settings/tokens")
    if status >= 400:
        raise ConnectionError(f"Hugging Face whoami failed ({status})")
    if not isinstance(payload, dict):
        raise ConnectionError("unexpected Hugging Face whoami response")
    name = payload.get("name") or payload.get("fullname") or ""
    return {
        "ok": True,
        "name": name,
        "type": payload.get("type") or "user",
        "can_read": True,
        "router": HF_ROUTER,
        "message": f"Connected as {name or 'Hugging Face user'}. Token stays in ~/.clawd/config.json.",
    }


def list_huggingface_models(token: str, search: str = "", *, limit: int = 30) -> list[dict[str, str]]:
    """List Hub text-generation models that advertise inference. User-initiated."""
    key = (token or "").strip()
    if not key:
        raise ValueError("Hugging Face token is required to list Hub models")
    query = {
        "pipeline_tag": "text-generation",
        "inference": "warm",
        "sort": "downloads",
        "direction": "-1",
        "limit": str(max(1, min(int(limit), 80))),
    }
    if search.strip():
        query["search"] = search.strip()
    status, payload = _request_json(f"{HF_MODELS}?{urlencode(query)}", token=key)
    if status >= 400:
        raise ConnectionError(f"Hugging Face model list failed ({status})")
    rows: list[dict[str, str]] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("modelId") or "")
            if not model_id:
                continue
            rows.append({
                "id": model_id,
                "downloads": str(item.get("downloads") or ""),
                "pipeline": str(item.get("pipeline_tag") or "text-generation"),
            })
    if not rows:
        rows = [{"id": name, "downloads": "", "pipeline": "text-generation"} for name in DEFAULT_HF_MODELS]
    return rows


def cache_huggingface_model(
    repo_id: str,
    token: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Download a Hub repo into ~/.clawd/hf-cache. User-initiated only."""
    model = (repo_id or "").strip()
    if not model or "/" not in model:
        raise ValueError("model id must look like org/name")
    key = (token or "").strip()
    if not key:
        raise ValueError("Hugging Face token is required to download Hub models")
    dest = hf_cache_root(home) / model.replace("/", "--")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "huggingface_hub is not installed. pip install huggingface_hub to cache Hub models."
        ) from exc
    path = snapshot_download(
        repo_id=model,
        token=key,
        local_dir=str(dest),
        local_dir_use_symlinks=False,
    )
    return {
        "ok": True,
        "repo_id": model,
        "path": str(path),
        "message": f"Cached {model} under {path}. Local-only; not uploaded.",
    }
