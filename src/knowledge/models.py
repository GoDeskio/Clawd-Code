"""Hugging Face ONNX embedding files with checksum checks.

The default model is the quantized ONNX build of BAAI/bge-small-en-v1.5
published by Qdrant on Hugging Face, which is the model fastembed loads.
Weights are accepted only from huggingface.co. Mirror hosts are refused
before any download starts. A checksum mismatch deletes the file.

Octop races an official Hugging Face download against hf-mirror and a COS
bucket. Jonathan Ai keeps the official host and the checksum, and does not
call those other hosts.

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

DEFAULT_MODEL_ID = "BAAI/bge-small-en-v1.5"
HF_REPO = "Qdrant/bge-small-en-v1.5-onnx-Q"
HF_HOST = "huggingface.co"

_BLOCKED_HOSTS = (
    "hf-mirror.com",
    "modelscope.cn",
    "modelscope.com",
    "npmmirror.com",
    "gitee.com",
    "ghproxy.com",
    "aliyuncs.com",
    "myqcloud.com",
)


class ModelSourceError(ValueError):
    """The model URL is not an allowlisted Hugging Face file."""


class ChecksumError(ValueError):
    """A model file did not match the pinned Hugging Face checksum."""


@dataclass(frozen=True)
class PinnedFile:
    name: str
    sha256: str
    size: int


# sha256 values were read from Hugging Face on 2026-10-10.
# model_optimized.onnx is the Git LFS oid. The other files are content hashes.
PINNED_FILES: tuple[PinnedFile, ...] = (
    PinnedFile(
        "model_optimized.onnx",
        "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431",
        66465124,
    ),
    PinnedFile(
        "config.json",
        "13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd",
        706,
    ),
    PinnedFile(
        "ort_config.json",
        "99881c45e073696289224931dd48694398bc6bcd1fe7cb7018bca1e0cc00e1fc",
        1272,
    ),
    PinnedFile(
        "special_tokens_map.json",
        "5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a",
        695,
    ),
    PinnedFile(
        "tokenizer_config.json",
        "0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53",
        1242,
    ),
    PinnedFile(
        "tokenizer.json",
        "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
        711396,
    ),
    PinnedFile(
        "vocab.txt",
        "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
        231508,
    ),
)

_PINNED_BY_NAME = {item.name: item for item in PINNED_FILES}


def file_url(name: str) -> str:
    if name not in _PINNED_BY_NAME:
        raise ModelSourceError(f"refusing model file {name}")
    return f"https://{HF_HOST}/{HF_REPO}/resolve/main/{name}"


def assert_model_url(url: str, *, redirect: bool = False) -> None:
    """Refuse anything that is not the pinned Hugging Face model.

    Redirects may land on a huggingface.co CDN host. They still have to stay
    on that host over HTTPS. The first request must name a pinned file.
    """
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ModelSourceError(f"refusing model URL {url}")
    if parsed.query or parsed.fragment:
        raise ModelSourceError(f"refusing model URL {url}")
    if host.endswith(".cn") or any(host == blocked or host.endswith("." + blocked) for blocked in _BLOCKED_HOSTS):
        raise ModelSourceError(f"refusing model host {host}")
    if host != HF_HOST and not host.endswith("." + HF_HOST):
        raise ModelSourceError(f"refusing model host {host}")
    if redirect:
        return
    if host != HF_HOST:
        raise ModelSourceError(f"refusing model host {host}")
    prefix = f"/{HF_REPO}/resolve/main/"
    if not parsed.path.startswith(prefix):
        raise ModelSourceError(f"refusing model path {parsed.path}")
    name = parsed.path[len(prefix) :]
    if name not in _PINNED_BY_NAME:
        raise ModelSourceError(f"refusing model file {name}")


def assert_cloud_embed_url(url: str) -> None:
    """Cloud document embeddings go only to the official OpenAI endpoint."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host != "api.openai.com" or parsed.username:
        raise ModelSourceError(f"refusing embedding host {host or url}")
    if host.endswith(".cn") or any(blocked in host for blocked in _BLOCKED_HOSTS):
        raise ModelSourceError(f"refusing embedding host {host}")
    if parsed.path.rstrip("/") != "/v1/embeddings":
        raise ModelSourceError("refusing embedding path")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_model_dir(model_dir: Path) -> bool:
    """Return True when every pinned file is present and matches.

    Missing files mean the model is not installed, so search can use BM25.
    A file that exists and does not match is deleted, and this raises.
    """
    saw_file = False
    for item in PINNED_FILES:
        path = model_dir / item.name
        if not path.is_file():
            continue
        saw_file = True
        if path.stat().st_size != item.size or sha256_file(path) != item.sha256:
            path.unlink()
            raise ChecksumError(f"checksum mismatch for {item.name}; file discarded")
    if not saw_file:
        return False
    return all((model_dir / item.name).is_file() for item in PINNED_FILES)


def store_verified_bytes(dest: Path, data: bytes, item: PinnedFile) -> None:
    """Write ``data`` only when it matches ``item``. A mismatch leaves nothing."""
    if len(data) != item.size or sha256_bytes(data) != item.sha256:
        if dest.exists():
            dest.unlink()
        raise ChecksumError(f"checksum mismatch for {item.name}; file discarded")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def read_model_bytes(url: str, fetch: Callable[[str], bytes]) -> bytes:
    """Check the URL, then download. ``fetch`` is not called for a refused host."""
    assert_model_url(url)
    return fetch(url)


def download_model(model_dir: Path, fetch: Callable[[str], bytes]) -> None:
    """Download each pinned file through ``fetch`` and keep it only if it matches."""
    model_dir.mkdir(parents=True, exist_ok=True)
    for item in PINNED_FILES:
        data = read_model_bytes(file_url(item.name), fetch)
        store_verified_bytes(model_dir / item.name, data, item)


def _redirect_handler() -> type[urllib.request.HTTPRedirectHandler]:
    class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            assert_model_url(newurl, redirect=True)
            return urllib.request.HTTPRedirectHandler.redirect_request(
                self, req, fp, code, msg, headers, newurl
            )

    return _CheckedRedirect


def default_fetch(url: str) -> bytes:
    """Download one allowlisted model URL. Redirects must stay on Hugging Face."""
    assert_model_url(url)
    previous_endpoint = os.environ.get("HF_ENDPOINT")
    os.environ["HF_ENDPOINT"] = f"https://{HF_HOST}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "jonathan-ai-kb"})
        opener = urllib.request.build_opener(_redirect_handler())
        with opener.open(request, timeout=120) as response:
            return response.read()
    finally:
        if previous_endpoint is None:
            os.environ.pop("HF_ENDPOINT", None)
        else:
            os.environ["HF_ENDPOINT"] = previous_endpoint
