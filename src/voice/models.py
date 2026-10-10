"""Official voice-model sources and checksums.

Models come from Hugging Face or the official Piper and Whisper repositories.
Downloads from other hosts, including mirrors, are refused before any request
is made. Checksums are the SHA-256 digests published with those files.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class VoiceError(ValueError):
    """A voice setting or model request cannot be completed."""


VOICE_EXTRA_HINT = 'Voice extra is not installed. Run: pip install "clawd-codex[voice]"'

_BLOCKED_MARKERS = (
    "hf-mirror.com",
    "hf-mirror",
    "modelscope.cn",
    "modelscope.com",
    "gitee.com",
    "ghproxy.com",
    "mirror.ghproxy.com",
    "aliyuncs.com",
    "myqcloud.com",
    "tencentcloudapi.com",
    "xiaomimimo.com",
)

_GITHUB_PREFIXES = (
    "/rhasspy/piper",
    "/rhasspy/piper-voices",
    "/SYSTRAN/faster-whisper",
    "/openai/whisper",
)

_ASSET_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class VoiceModel:
    model_id: str
    role: str
    files: tuple[ModelFile, ...]


WHISPER_TINY = VoiceModel(
    model_id="faster-whisper-tiny",
    role="stt",
    files=(
        ModelFile(
            name="model.bin",
            url="https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/model.bin",
            sha256="dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1",
            size=75538270,
        ),
        ModelFile(
            name="config.json",
            url="https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/config.json",
            sha256="a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8",
            size=2249,
        ),
        ModelFile(
            name="tokenizer.json",
            url="https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/tokenizer.json",
            sha256="fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
            size=2203239,
        ),
        ModelFile(
            name="vocabulary.txt",
            url="https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/vocabulary.txt",
            sha256="34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
            size=459861,
        ),
    ),
)

PIPER_LESSAC = VoiceModel(
    model_id="en_US-lessac-medium",
    role="tts",
    files=(
        ModelFile(
            name="en_US-lessac-medium.onnx",
            url=(
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                "en/en_US/lessac/medium/en_US-lessac-medium.onnx"
            ),
            sha256="5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
            size=63201294,
        ),
        ModelFile(
            name="en_US-lessac-medium.onnx.json",
            url=(
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
            ),
            sha256="efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0",
            size=4885,
        ),
    ),
)

CATALOG: dict[str, VoiceModel] = {
    WHISPER_TINY.model_id: WHISPER_TINY,
    PIPER_LESSAC.model_id: PIPER_LESSAC,
}

CLOUD_ENDPOINTS = {
    "openai": {
        "stt": "https://api.openai.com/v1/audio/transcriptions",
        "tts": "https://api.openai.com/v1/audio/speech",
    },
    "xai": {
        "stt": "https://api.x.ai/v1/audio/transcriptions",
        "tts": "https://api.x.ai/v1/audio/speech",
    },
}


def catalog_model(model_id: str) -> VoiceModel:
    try:
        return CATALOG[model_id]
    except KeyError as exc:
        known = ", ".join(sorted(CATALOG))
        raise VoiceError(f"Unknown voice model {model_id!r}. Known models: {known}.") from exc


def assert_model_url(url: str) -> str:
    """Refuse every model URL that is not Hugging Face or an official source."""
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    lowered = url.lower()
    if parsed.scheme != "https" or not host:
        raise VoiceError(f"Refusing model URL {url!r}.")
    if host.endswith(".cn") or any(marker in host or marker in lowered for marker in _BLOCKED_MARKERS):
        raise VoiceError(f"Refusing model host {host}. Use Hugging Face or the official project source.")
    huggingface = host == "huggingface.co" or host.endswith(".huggingface.co")
    if huggingface:
        return url
    if host == "github.com":
        if any(parsed.path.startswith(prefix) for prefix in _GITHUB_PREFIXES):
            return url
        raise VoiceError("GitHub model downloads are limited to official Piper and Whisper repositories.")
    if host in _ASSET_HOSTS:
        return url
    raise VoiceError(f"Refusing model host {host}. Use Hugging Face or the official project source.")


def assert_cloud_url(url: str) -> str:
    """Cloud audio is sent only to the selected provider's official endpoint."""
    target = url.strip()
    allowed = {item for endpoints in CLOUD_ENDPOINTS.values() for item in endpoints.values()}
    if target not in allowed:
        raise VoiceError("Refusing voice request to an unknown cloud endpoint.")
    return target


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_sha256: str, expected_size: int | None = None) -> None:
    if not path.is_file():
        raise VoiceError(
            f"Missing {path.name}. Download it from Hugging Face or the official source with /voice download."
        )
    if expected_size is not None and path.stat().st_size != expected_size:
        raise VoiceError(f"Checksum mismatch for {path.name}: file size does not match the official file.")
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise VoiceError(f"Checksum mismatch for {path.name}.")


def verify_installed(root: Path, model: VoiceModel) -> Path:
    folder = root / model.model_id
    for item in model.files:
        assert_model_url(item.url)
        verify_file(folder / item.name, item.sha256, item.size)
    return folder


def download_model(model_id: str, dest: Path, *, fetch) -> Path:
    """Download one catalog model. ``fetch`` is called only after the URL is allowed."""
    model = catalog_model(model_id)
    folder = dest / model.model_id
    folder.mkdir(parents=True, exist_ok=True)
    for item in model.files:
        assert_model_url(item.url)
        data = fetch(item.url)
        digest = hashlib.sha256(data).hexdigest()
        if digest != item.sha256 or len(data) != item.size:
            raise VoiceError(f"Checksum mismatch for {item.name}. The download was discarded.")
        target = folder / item.name
        target.write_bytes(data)
    return folder


def download_url(url: str, dest: Path, *, fetch, expected_sha256: str) -> None:
    """Fetch one allowlisted URL. The fetch callback is not used when the host is refused."""
    assert_model_url(url)
    data = fetch(url)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise VoiceError(f"Checksum mismatch for {dest.name}. The download was discarded.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
