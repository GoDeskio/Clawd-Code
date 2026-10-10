"""Speech-to-text and text-to-speech.

Local faster-whisper and Piper are the defaults. OpenAI and xAI run only
when that provider is selected, and only against their official endpoints.
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from ..secret_mask import mask_secrets
from .models import (
    CLOUD_ENDPOINTS,
    VOICE_EXTRA_HINT,
    VoiceError,
    assert_cloud_url,
    catalog_model,
    verify_installed,
)
from .settings import LOCAL, cloud_api_key, models_dir

CloudPost = Callable[[str, dict[str, str], bytes, str], bytes]
LocalSpeech = Callable[[bytes, Path, str], str]
LocalVoice = Callable[[str, Path], bytes]


def transcribe(
    audio: bytes,
    settings: dict,
    *,
    directory: Path | None = None,
    local_engine: LocalSpeech | None = None,
    transport: CloudPost | None = None,
) -> str:
    provider = str(settings.get("stt_provider") or LOCAL)
    if provider == LOCAL:
        engine = local_engine or _whisper_transcribe
        model = catalog_model(str(settings.get("stt_model") or "faster-whisper-tiny"))
        if model.role != "stt":
            raise VoiceError(f"{model.model_id} is not a speech-to-text model.")
        folder = verify_installed(models_dir(directory), model)
        return engine(audio, folder, str(settings.get("language") or "en")).strip()
    if provider not in CLOUD_ENDPOINTS:
        raise VoiceError("Speech provider must be local, openai, or xai.")
    return _cloud_transcribe(audio, settings, provider, transport)


def synthesize(
    text: str,
    settings: dict,
    *,
    directory: Path | None = None,
    local_engine: LocalVoice | None = None,
    transport: CloudPost | None = None,
) -> bytes:
    spoken = " ".join(str(text or "").split())
    if not spoken:
        raise VoiceError("There is nothing to say.")
    provider = str(settings.get("tts_provider") or LOCAL)
    if provider == LOCAL:
        engine = local_engine or _piper_synthesize
        model = catalog_model(str(settings.get("tts_voice") or "en_US-lessac-medium"))
        if model.role != "tts":
            raise VoiceError(f"{model.model_id} is not a text-to-speech voice.")
        folder = verify_installed(models_dir(directory), model)
        return engine(spoken, folder)
    if provider not in CLOUD_ENDPOINTS:
        raise VoiceError("Voice provider must be local, openai, or xai.")
    return _cloud_synthesize(spoken, settings, provider, transport)


def _cloud_transcribe(audio: bytes, settings: dict, provider: str, transport: CloudPost | None) -> str:
    key = cloud_api_key(provider, settings)
    if not key:
        raise VoiceError(f"{provider} speech-to-text needs an API key. Audio was not sent.")
    url = assert_cloud_url(CLOUD_ENDPOINTS[provider]["stt"])
    language = str(settings.get("language") or "en").split("-")[0]
    body, content_type = _multipart(
        {"model": "whisper-1", "language": language},
        filename="speech.wav",
        content=audio,
        mime="audio/wav",
    )
    raw = _post(url, key, body, content_type, transport)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VoiceError("Cloud speech-to-text returned an unreadable response.") from exc
    return str(payload.get("text") or "").strip()


def _cloud_synthesize(text: str, settings: dict, provider: str, transport: CloudPost | None) -> bytes:
    key = cloud_api_key(provider, settings)
    if not key:
        raise VoiceError(f"{provider} text-to-speech needs an API key. The request was not sent.")
    url = assert_cloud_url(CLOUD_ENDPOINTS[provider]["tts"])
    payload = json.dumps(
        {
            "model": "tts-1",
            "input": text,
            "voice": str(settings.get("cloud_voice") or "alloy"),
            "response_format": "wav",
        }
    ).encode("utf-8")
    return _post(url, key, payload, "application/json", transport)


def _post(url: str, key: str, body: bytes, content_type: str, transport: CloudPost | None) -> bytes:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": content_type}
    sender = transport or _urllib_post
    try:
        return sender(url, headers, body, content_type)
    except VoiceError:
        raise
    except Exception as exc:
        raise VoiceError(mask_secrets(str(exc))) from exc


def _urllib_post(url: str, headers: dict[str, str], body: bytes, content_type: str) -> bytes:
    assert_cloud_url(url)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(_RefuseRedirects)
    with opener.open(request, timeout=60) as response:
        return response.read()


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise VoiceError("Cloud voice endpoint must not redirect.")


def _multipart(fields: dict[str, str], *, filename: str, content: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "jonvoice" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    chunks.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
        + content
        + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _whisper_transcribe(audio: bytes, model_dir: Path, language: str) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VoiceError(VOICE_EXTRA_HINT) from exc
    import tempfile

    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(audio)
        temp_name = handle.name
    try:
        segments, _info = model.transcribe(temp_name, language=language or None)
        return "".join(segment.text for segment in segments)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _load_piper():
    try:
        from piper.voice import PiperVoice
    except ImportError:
        PiperVoice = None
    if PiperVoice is None:
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise VoiceError(VOICE_EXTRA_HINT) from exc
    return PiperVoice


def _piper_synthesize(text: str, model_dir: Path) -> bytes:
    PiperVoice = _load_piper()
    import io
    import wave

    voice_path = next(model_dir.glob("*.onnx"))
    voice = PiperVoice.load(str(voice_path))
    if hasattr(voice, "synthesize_stream_raw"):
        pcm = b"".join(voice.synthesize_stream_raw(text))
        sample_rate = int(getattr(voice.config, "sample_rate", 22050) or 22050)
        return _pcm16_wav(pcm, sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        voice.synthesize(text, wav)
    return buffer.getvalue()


def _pcm16_wav(pcm: bytes, sample_rate: int) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()
