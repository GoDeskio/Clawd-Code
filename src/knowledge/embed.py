"""Local fastembed embeddings, with an explicit OpenAI cloud path.

The local engine is imported only when a verified model directory is
embedded. Search falls back to BM25 when the extra or the model is absent.
Cloud embeddings run only after the caller has selected that provider, and
only against api.openai.com.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable
from pathlib import Path

from src.knowledge.models import (
    DEFAULT_MODEL_ID,
    HF_HOST,
    ChecksumError,
    assert_cloud_embed_url,
    verify_model_dir,
)

CLOUD_EMBED_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_CLOUD_MODEL = "text-embedding-3-small"
_LOCAL_EXTRA = 'Local embeddings need the optional knowledge extra: pip install "clawd-codex[kb]"'
_NOT_SENT = "cloud embedding key is not set; document text was not sent"

Transport = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]
Embedder = Callable[[list[str]], list[list[float]]]


def embed_local(
    texts: list[str],
    model_dir: Path,
    *,
    embedder: Embedder | None = None,
) -> list[list[float]] | None:
    """Embed with the injected engine or fastembed.

    Returns None when the local model is not on disk and no engine was
    injected, so the caller can rank with BM25. A checksum mismatch still
    raises after the bad file is removed.
    """
    if not texts:
        return []
    if embedder is not None:
        return [_as_floats(row) for row in embedder(texts)]
    try:
        ready = verify_model_dir(model_dir)
    except ChecksumError:
        return None
    if not ready:
        return None
    return _fastembed(texts, model_dir)


def embed_cloud(
    texts: list[str],
    *,
    api_key: str,
    model: str,
    transport: Transport | None = None,
    url: str = CLOUD_EMBED_URL,
) -> list[list[float]]:
    """Send texts to the selected cloud embedder. Refuses other hosts first."""
    if not texts:
        return []
    if not api_key.strip():
        raise RuntimeError(_NOT_SENT)
    assert_cloud_embed_url(url)
    sender = transport or _urllib_transport
    payload = sender(
        url,
        {"model": model.strip() or DEFAULT_CLOUD_MODEL, "input": list(texts)},
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    return _vectors_from_response(payload, expected=len(texts))


def _fastembed(texts: list[str], model_dir: Path) -> list[list[float]]:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise RuntimeError(_LOCAL_EXTRA) from exc
    saved = {
        "HF_ENDPOINT": os.environ.get("HF_ENDPOINT"),
        "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
    }
    os.environ["HF_ENDPOINT"] = f"https://{HF_HOST}"
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        engine = TextEmbedding(
            model_name=DEFAULT_MODEL_ID,
            specific_model_path=str(model_dir),
            local_files_only=True,
        )
        vectors = list(engine.embed(texts))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return [_as_floats(row) for row in vectors]


def _as_floats(row: Any) -> list[float]:
    values = row.tolist() if hasattr(row, "tolist") else list(row)
    floats = [float(value) for value in values]
    if not floats:
        raise RuntimeError("embedding was empty")
    return floats


def _vectors_from_response(payload: dict[str, Any], *, expected: int) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("embedding response has no data")
    ordered = sorted(
        data,
        key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0,
    )
    vectors = [_as_floats(item["embedding"]) for item in ordered if isinstance(item, dict)]
    if len(vectors) != expected:
        raise RuntimeError("embedding count mismatch")
    return vectors


def _urllib_transport(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    assert_cloud_embed_url(url)
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("embedding response was not an object")
    return parsed
