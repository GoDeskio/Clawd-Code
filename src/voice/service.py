"""Voice command, settings snapshot, and desktop push-to-talk control."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .devices import AudioBackend, SoundDeviceBackend, list_devices
from .engines import synthesize, transcribe
from .models import VoiceError, catalog_model, download_model
from .session import PushToTalk
from .settings import audio_stays_local, load_settings, public_settings, update_settings, voice_dir

_CONTROLLER: PushToTalk | None = None
_CONTROLLER_LOCK = threading.Lock()


def voice_status(
    directory: Path | None = None,
    *,
    backend: AudioBackend | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    settings = load_settings(directory)
    device_error = ""
    devices: list[dict[str, Any]] = []
    try:
        devices = [device.to_dict() for device in list_devices(backend, platform=platform)]
    except VoiceError as exc:
        device_error = str(exc)
    return {
        "settings": public_settings(settings),
        "devices": devices,
        "device_error": device_error,
        "providers": [
            {"id": "local", "label": "Local (Whisper and Piper)", "cloud": False},
            {"id": "openai", "label": "OpenAI", "cloud": True},
            {"id": "xai", "label": "xAI", "cloud": True},
        ],
        "install": 'pip install "clawd-codex[voice]"',
    }


def apply_voice_settings(changes: dict[str, Any], directory: Path | None = None) -> dict[str, Any]:
    public = update_settings(changes, directory)
    return voice_status(directory) | {"settings": public}


def speak(
    text: str,
    *,
    directory: Path | None = None,
    synthesizer=None,
    player=None,
    transport=None,
) -> str:
    settings = load_settings(directory)
    audio = synthesize(text, settings, directory=directory, local_engine=synthesizer, transport=transport)
    output = str(settings.get("output_device") or "")
    if player is None:
        player = SoundDeviceBackend().write
    player(output, audio)
    if settings.get("tts_provider") == "local":
        where = "on this machine"
    else:
        where = f"with {settings.get('tts_provider')}"
    speaker = output or "the default speaker"
    return f"Spoke {len(audio)} bytes through {speaker} ({where})."


def transcribe_audio(
    audio: bytes,
    *,
    directory: Path | None = None,
    local_engine=None,
    transport=None,
) -> str:
    settings = load_settings(directory)
    return transcribe(audio, settings, directory=directory, local_engine=local_engine, transport=transport)


def fetch_models(directory: Path | None = None, *, fetch) -> str:
    """Download the configured local models from their allowlisted URLs."""
    settings = load_settings(directory)
    root = (directory or voice_dir()) / "models"
    written = []
    for model_id in (settings["stt_model"], settings["tts_voice"]):
        catalog_model(model_id)
        download_model(model_id, root, fetch=fetch)
        written.append(model_id)
    return "Downloaded " + " and ".join(written) + " from Hugging Face after checksum verification."


def set_controller(controller: PushToTalk | None) -> None:
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        _CONTROLLER = controller


def _default_controller() -> PushToTalk:
    backend = SoundDeviceBackend()

    def read_frame(device_id: str) -> bytes:
        return backend.read(device_id)

    def _transcribe(audio: bytes) -> str:
        return transcribe_audio(audio)

    return PushToTalk(read_frame, _transcribe)


def push_to_talk_action(action: str, *, directory: Path | None = None) -> dict[str, Any]:
    settings = load_settings(directory)
    if not settings.get("push_to_talk", True):
        raise VoiceError("Push-to-talk is off. Turn it on with /voice ptt on.")
    with _CONTROLLER_LOCK:
        controller = _CONTROLLER or _default_controller()
    name = str(action or "").strip().lower()
    if name == "start":
        controller.start(str(settings.get("input_device") or ""))
        return {"holding": True, "audio_stays_local": audio_stays_local(settings)}
    if name == "stop":
        text = controller.stop()
        return {"holding": False, "text": text, "audio_stays_local": audio_stays_local(settings)}
    raise VoiceError("Push-to-talk action must be start or stop.")


def format_voice_command(
    args: str,
    *,
    directory: Path | None = None,
    backend: AudioBackend | None = None,
    platform: str | None = None,
    synthesizer=None,
    player=None,
    transport=None,
    fetch=None,
) -> str:
    text = " ".join(str(args or "").split())
    head, _, rest = text.partition(" ")
    command = head.lower()
    try:
        if command in {"", "settings", "status"}:
            return _format_status(voice_status(directory, backend=backend, platform=platform))
        if command == "devices":
            return _format_devices(voice_status(directory, backend=backend, platform=platform))
        if command == "stt":
            public = update_settings({"stt_provider": rest}, directory)
            return _provider_line("Speech-to-text", public)
        if command == "tts":
            public = update_settings({"tts_provider": rest}, directory)
            return _provider_line("Text-to-speech", public)
        if command == "input":
            update_settings({"input_device": rest}, directory)
            return f"Microphone set to {rest or 'the default input'}."
        if command == "output":
            update_settings({"output_device": rest}, directory)
            return f"Speaker set to {rest or 'the default output'}."
        if command == "ptt":
            enabled = update_settings({"push_to_talk": rest or "on"}, directory)["push_to_talk"]
            return "Push-to-talk is on." if enabled else "Push-to-talk is off."
        if command == "wake":
            return _wake_command(rest, directory)
        if command == "say":
            return speak(rest, directory=directory, synthesizer=synthesizer, player=player, transport=transport)
        if command == "download":
            if fetch is None:
                raise VoiceError("Model download is not configured.")
            return fetch_models(directory, fetch=fetch)
        if command == "language":
            public = update_settings({"language": rest or "en"}, directory)
            return f"Language set to {public['language']}."
    except VoiceError as exc:
        return str(exc)
    return (
        "Usage: /voice [settings | devices | stt local|openai|xai | tts local|openai|xai | "
        "input <id> | output <id> | ptt on|off | wake on|off [phrase] | say <text> | language <code>]"
    )


def _wake_command(rest: str, directory: Path | None) -> str:
    parts = rest.split(maxsplit=1)
    if not parts:
        raise VoiceError("Usage: /voice wake on|off [phrase]")
    changes: dict[str, Any] = {"wake_word_enabled": parts[0]}
    if len(parts) == 2:
        changes["wake_word"] = parts[1]
    public = update_settings(changes, directory)
    state = "on" if public["wake_word_enabled"] else "off"
    return (
        f"Wake word is {state} ({public['wake_word']}). "
        "The check stays on this machine and is off until you enable it."
    )


def _provider_line(label: str, public: dict[str, Any]) -> str:
    key = "stt_provider" if label.startswith("Speech") else "tts_provider"
    stay = "Audio stays on this machine." if public["audio_stays_local"] else public["note"]
    return f"{label} set to {public[key]}. {stay}"


def _format_status(status: dict[str, Any]) -> str:
    settings = status["settings"]
    lines = [
        f"Speech-to-text: {settings['stt_provider']} ({settings['stt_model']})",
        f"Text-to-speech: {settings['tts_provider']} ({settings['tts_voice']})",
        f"Microphone: {settings['input_device'] or 'default'}",
        f"Speaker: {settings['output_device'] or 'default'}",
        f"Push-to-talk: {'on' if settings['push_to_talk'] else 'off'}",
        f"Wake word: {'on' if settings['wake_word_enabled'] else 'off'} ({settings['wake_word']})",
        f"Language: {settings['language']}",
        settings["note"],
        f"Voice extra: {status['install']}",
    ]
    if status.get("device_error"):
        lines.append(status["device_error"])
    return "\n".join(lines)


def _format_devices(status: dict[str, Any]) -> str:
    devices = status.get("devices") or []
    if not devices:
        detail = status.get("device_error") or "No audio devices reported."
        return detail
    lines = []
    for device in devices:
        marks = [device["kind"], device["host_api"]]
        if device.get("bluetooth"):
            marks.append("Bluetooth")
        if device.get("default"):
            marks.append("default")
        lines.append(f"{device['id']}: {device['name']} ({', '.join(marks)})")
    return "\n".join(lines)
