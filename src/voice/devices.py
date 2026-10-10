"""Input and output device selection for Windows WASAPI and Linux PulseAudio.

Bluetooth headsets and speakers are ordinary devices on those host APIs.
Tests pass a fake backend so PortAudio is never required.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from .models import VOICE_EXTRA_HINT, VoiceError


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    kind: str
    host_api: str
    is_bluetooth: bool
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bluetooth"] = payload.pop("is_bluetooth")
        payload["default"] = payload.pop("is_default")
        return payload


class AudioBackend(Protocol):
    def list_devices(self) -> list[AudioDevice]:
        """Return every input and output the host currently exposes."""

    def read(self, device_id: str) -> bytes:
        """Capture one short chunk from the selected input."""

    def write(self, device_id: str, audio: bytes) -> None:
        """Play one buffer on the selected output."""


def is_bluetooth(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("bluetooth", "bluez", "bt-sco", "airpods"))


def host_matches_platform(host_api: str, platform: str) -> bool:
    host = host_api.lower()
    if platform == "win32":
        return "wasapi" in host
    if platform.startswith("linux"):
        return "pulse" in host or "pipewire" in host or "pipe" in host
    return True


def filter_for_platform(devices: list[AudioDevice], platform: str | None = None) -> list[AudioDevice]:
    system = platform if platform is not None else sys.platform
    matched = [device for device in devices if host_matches_platform(device.host_api, system)]
    return matched or list(devices)


def list_devices(backend: AudioBackend | None = None, *, platform: str | None = None) -> list[AudioDevice]:
    if backend is not None:
        return filter_for_platform(list(backend.list_devices()), platform)
    try:
        discovered = _query_sounddevice()
    except VoiceError:
        raise
    except Exception as exc:
        raise VoiceError(VOICE_EXTRA_HINT) from exc
    return filter_for_platform(discovered, platform)


def _query_sounddevice() -> list[AudioDevice]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise VoiceError(VOICE_EXTRA_HINT) from exc
    hostapis = list(sd.query_hostapis())
    devices = list(sd.query_devices())
    defaults = getattr(sd.default, "device", (None, None))
    default_in = defaults[0] if isinstance(defaults, (list, tuple)) and defaults else None
    default_out = defaults[1] if isinstance(defaults, (list, tuple)) and len(defaults) > 1 else None
    found: list[AudioDevice] = []
    for index, dev in enumerate(devices):
        host_name = str(hostapis[int(dev["hostapi"])]["name"])
        name = str(dev["name"])
        if int(dev.get("max_input_channels") or 0) > 0:
            found.append(
                AudioDevice(
                    id=str(index),
                    name=name,
                    kind="input",
                    host_api=host_name,
                    is_bluetooth=is_bluetooth(name),
                    is_default=index == default_in,
                )
            )
        if int(dev.get("max_output_channels") or 0) > 0:
            found.append(
                AudioDevice(
                    id=str(index),
                    name=name,
                    kind="output",
                    host_api=host_name,
                    is_bluetooth=is_bluetooth(name),
                    is_default=index == default_out,
                )
            )
    return found


class SoundDeviceBackend:
    """PortAudio backend. Windows uses WASAPI; Linux uses PulseAudio or PipeWire."""

    def list_devices(self) -> list[AudioDevice]:
        return _query_sounddevice()

    def read(self, device_id: str) -> bytes:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise VoiceError(VOICE_EXTRA_HINT) from exc
        device = int(device_id) if str(device_id).isdigit() else None
        audio = sd.rec(int(0.2 * 16000), samplerate=16000, channels=1, dtype="int16", device=device)
        sd.wait()
        return audio.tobytes()

    def write(self, device_id: str, audio: bytes) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise VoiceError(VOICE_EXTRA_HINT) from exc
        import array
        import io
        import wave

        with wave.open(io.BytesIO(audio), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
            rate = wav.getframerate()
        samples = array.array("h")
        samples.frombytes(frames)
        device = int(device_id) if str(device_id).isdigit() else None
        sd.play(samples, samplerate=rate, device=device)
        sd.wait()
