"""Voice tests. Audio engines and PortAudio are mocked; no model is downloaded."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.command_system.builtins import execute_command_sync
from src.command_system.engine import create_command_context
from src.desktop.server import DesktopServer
from src.voice import ARCHIVE_NAME, SAMPLE_FILES
from src.voice.devices import AudioDevice, filter_for_platform, is_bluetooth
from src.voice.engines import synthesize, transcribe
from src.voice.models import (
    ModelFile,
    VoiceError,
    VoiceModel,
    assert_cloud_url,
    assert_model_url,
    download_url,
    verify_file,
)
from src.voice.service import (
    format_voice_command,
    push_to_talk_action,
    set_controller,
    speak,
    voice_status,
)
from src.voice.session import PushToTalk, capture_while_held, hear_wake_word, local_phrase_detector
from src.voice.settings import load_settings, public_settings, update_settings


def _model(payload: bytes, *, model_id: str, role: str, name: str) -> VoiceModel:
    return VoiceModel(
        model_id=model_id,
        role=role,
        files=(
            ModelFile(
                name=name,
                url="https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/model.bin",
                sha256=hashlib.sha256(payload).hexdigest(),
                size=len(payload),
            ),
        ),
    )


class VoiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.voice = Path(self.tmp.name) / "voice"
        self.voice.mkdir()
        self.env = patch.dict(
            os.environ,
            {"JONATHAN_VOICE_DIR": str(self.voice), "OPENAI_API_KEY": "", "XAI_API_KEY": ""},
        )
        self.env.start()
        set_controller(None)

    def tearDown(self) -> None:
        set_controller(None)
        self.env.stop()
        self.tmp.cleanup()

    def _plant(self, model: VoiceModel, payload: bytes) -> None:
        folder = self.voice / "models" / model.model_id
        folder.mkdir(parents=True)
        (folder / model.files[0].name).write_bytes(payload)


class TestDefaultsAndSettings(VoiceTestCase):
    def test_defaults_are_local_english_and_push_to_talk(self) -> None:
        settings = load_settings(self.voice)
        self.assertEqual(settings["stt_provider"], "local")
        self.assertEqual(settings["tts_provider"], "local")
        self.assertEqual(settings["language"], "en")
        self.assertTrue(settings["push_to_talk"])
        self.assertFalse(settings["wake_word_enabled"])
        self.assertTrue(public_settings(settings)["audio_stays_local"])

    def test_cloud_provider_is_explicit_and_keys_stay_out_of_the_view(self) -> None:
        secret = "sk-" + ("a" * 24)
        public = update_settings(
            {"stt_provider": "openai", "openai_api_key": secret, "tts_provider": "xai", "xai_api_key": "xai-secret-value"},
            self.voice,
        )
        self.assertEqual(public["stt_provider"], "openai")
        self.assertEqual(public["tts_provider"], "xai")
        self.assertFalse(public["audio_stays_local"])
        self.assertNotIn(secret, json.dumps(public))
        self.assertNotIn("xai-secret-value", json.dumps(public))
        shown = format_voice_command("settings", directory=self.voice, backend=_EmptyBackend())
        self.assertNotIn(secret, shown)
        self.assertIn("cloud provider", shown)
        stored = (self.voice / next(self.voice.glob("settings-*.json"))).read_text(encoding="utf-8")
        self.assertIn(secret, stored)

    def test_users_do_not_share_settings(self) -> None:
        with patch("src.agent.memory.current_user_id", return_value="ada"):
            update_settings({"input_device": "ada-mic"}, self.voice)
        with patch("src.agent.memory.current_user_id", return_value="bob"):
            update_settings({"input_device": "bob-mic"}, self.voice)
            bob = load_settings(self.voice)
        with patch("src.agent.memory.current_user_id", return_value="ada"):
            ada = load_settings(self.voice)
        self.assertEqual(ada["input_device"], "ada-mic")
        self.assertEqual(bob["input_device"], "bob-mic")

    def test_rejects_unknown_provider(self) -> None:
        for name in ("tencent", "edge", "mimo", "browser"):
            with self.assertRaises(VoiceError):
                update_settings({"stt_provider": name}, self.voice)


class TestModels(VoiceTestCase):
    def test_refuses_mirrors_before_any_fetch(self) -> None:
        calls: list[str] = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            return b"nope"

        blocked = (
            "https://hf-mirror.com/Systran/faster-whisper-tiny/resolve/main/model.bin",
            "https://www.modelscope.cn/models/whisper/model.bin",
            "http://huggingface.co/Systran/faster-whisper-tiny/resolve/main/model.bin",
            "https://github.com/evil/piper/releases/model.onnx",
            "https://example.cn/model.bin",
            "https://mirror.ghproxy.com/https://github.com/rhasspy/piper/model.onnx",
            "https://api.xiaomimimo.com/v1/audio",
        )
        for url in blocked:
            with self.assertRaises(VoiceError):
                download_url(url, self.voice / "model.bin", fetch=fetch, expected_sha256="abc")
        self.assertEqual(calls, [])

    def test_allows_hugging_face_and_official_piper(self) -> None:
        assert_model_url("https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/model.bin")
        assert_model_url(
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
        )
        assert_model_url("https://github.com/rhasspy/piper/releases/download/v1/voice.onnx")
        assert_cloud_url("https://api.openai.com/v1/audio/transcriptions")
        assert_cloud_url("https://api.x.ai/v1/audio/speech")
        with self.assertRaises(VoiceError):
            assert_cloud_url("https://api.openai.com/v1/chat/completions")

    def test_checksum_mismatch_discards_the_file(self) -> None:
        dest = self.voice / "model.bin"
        url = "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/model.bin"
        with self.assertRaises(VoiceError) as raised:
            download_url(url, dest, fetch=lambda _url: b"not-the-model", expected_sha256="0" * 64)
        self.assertIn("Checksum mismatch", str(raised.exception))
        self.assertFalse(dest.exists())

    def test_checksum_match_keeps_the_file(self) -> None:
        payload = b"official-bytes"
        dest = self.voice / "nested" / "model.bin"
        url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
        download_url(url, dest, fetch=lambda _url: payload, expected_sha256=hashlib.sha256(payload).hexdigest())
        self.assertEqual(dest.read_bytes(), payload)
        with self.assertRaises(VoiceError):
            verify_file(dest, "f" * 64, len(payload))


class TestSpeech(VoiceTestCase):
    def test_local_transcribe_never_calls_the_network(self) -> None:
        payload = b"weights"
        model = _model(payload, model_id="tiny-test", role="stt", name="model.bin")
        self._plant(model, payload)
        calls: list[object] = []

        def engine(audio: bytes, folder: Path, language: str) -> str:
            self.assertEqual(audio, b"mic")
            self.assertEqual(language, "en")
            self.assertTrue((folder / "model.bin").is_file())
            return "local words"

        def transport(*args: object) -> bytes:
            calls.append(args)
            return b"{}"

        def exploded(*_args: object, **_kwargs: object) -> bytes:
            raise AssertionError("local speech tried to use the network")

        with patch("src.voice.engines.catalog_model", return_value=model), patch(
            "urllib.request.urlopen", exploded
        ):
            text = transcribe(
                b"mic",
                {"stt_provider": "local", "stt_model": "tiny-test", "language": "en"},
                directory=self.voice,
                local_engine=engine,
                transport=transport,
            )
        self.assertEqual(text, "local words")
        self.assertEqual(calls, [])

    def test_bad_checksum_does_not_load_the_engine(self) -> None:
        payload = b"nope"
        model = _model(b"expected", model_id="tiny-test", role="stt", name="model.bin")
        self._plant(model, payload)
        called: list[bytes] = []
        with patch("src.voice.engines.catalog_model", return_value=model):
            with self.assertRaises(VoiceError):
                transcribe(
                    b"mic",
                    {"stt_provider": "local", "stt_model": "tiny-test", "language": "en"},
                    directory=self.voice,
                    local_engine=lambda *_args: called.append(b"x") or "no",
                )
        self.assertEqual(called, [])

    def test_openai_and_xai_are_used_only_when_selected(self) -> None:
        def transport(url: str, headers: dict[str, str], body: bytes, content_type: str) -> bytes:
            self.assertIn(url, {
                "https://api.openai.com/v1/audio/transcriptions",
                "https://api.x.ai/v1/audio/speech",
            })
            self.assertIn("Bearer", headers["Authorization"])
            self.assertNotIn("sk-secretsecretsecretsecret", url)
            if url.endswith("/speech"):
                return b"RIFFcloud"
            return b'{"text": "from openai"}'

        with patch("src.voice.settings._saved_openai_key", return_value=""):
            text = transcribe(
                b"mic",
                {"stt_provider": "openai", "openai_api_key": "sk-secretsecretsecretsecret", "language": "en"},
                directory=self.voice,
                transport=transport,
                local_engine=lambda *_args: (_ for _ in ()).throw(AssertionError("local engine used")),
            )
            audio = synthesize(
                "hello",
                {"tts_provider": "xai", "xai_api_key": "xai-key", "cloud_voice": "alloy"},
                directory=self.voice,
                transport=transport,
            )
        self.assertEqual(text, "from openai")
        self.assertEqual(audio, b"RIFFcloud")

    def test_cloud_without_a_key_sends_nothing(self) -> None:
        def transport(*_args: object) -> bytes:
            raise AssertionError("audio left the machine")

        with patch("src.voice.settings._saved_openai_key", return_value=""):
            with self.assertRaises(VoiceError) as raised:
                transcribe(
                    b"mic",
                    {"stt_provider": "openai", "openai_api_key": "", "language": "en"},
                    transport=transport,
                )
        self.assertIn("was not sent", str(raised.exception))

    def test_speak_plays_local_audio_on_the_selected_device(self) -> None:
        payload = b"voice-weights"
        model = _model(payload, model_id="piper-test", role="tts", name="voice.onnx")
        self._plant(model, payload)
        update_settings({"tts_provider": "local", "tts_voice": "piper-test", "output_device": "4"}, self.voice)
        played: list[tuple[str, bytes]] = []
        with patch("src.voice.engines.catalog_model", return_value=model):
            message = speak(
                "hello there",
                directory=self.voice,
                synthesizer=lambda text, folder: b"RIFF" + text.encode("utf-8"),
                player=lambda device, audio: played.append((device, audio)),
            )
        self.assertEqual(played, [("4", b"RIFFhello there")])
        self.assertIn("on this machine", message)


class TestDevicesAndCapture(VoiceTestCase):
    def test_windows_wasapi_and_linux_pulse_include_bluetooth(self) -> None:
        devices = [
            AudioDevice("1", "Microphone Array", "input", "MME", False),
            AudioDevice("2", "Headset (Bluetooth)", "input", "Windows WASAPI", True),
            AudioDevice("3", "Speakers", "output", "Windows WASAPI", False),
            AudioDevice("4", "bluez_output.AA_BB.a2dp-sink", "output", "PulseAudio", True),
            AudioDevice("5", "PipeWire mic", "input", "PipeWire", False),
        ]
        self.assertTrue(is_bluetooth("Headset (Bluetooth)"))
        self.assertTrue(is_bluetooth("bluez_output.AA_BB"))
        windows = filter_for_platform(devices, "win32")
        linux = filter_for_platform(devices, "linux")
        self.assertTrue(all("wasapi" in device.host_api.lower() for device in windows))
        self.assertTrue(any(device.is_bluetooth and device.kind == "input" for device in windows))
        self.assertTrue(all("pulse" in device.host_api.lower() or "pipe" in device.host_api.lower() for device in linux))
        self.assertTrue(any(device.is_bluetooth for device in linux))
        listed = format_voice_command("devices", directory=self.voice, backend=_Backend(devices), platform="linux")
        self.assertIn("Bluetooth", listed)
        self.assertIn("bluez_output", listed)
        self.assertNotIn("MME", listed)

    def test_push_to_talk_records_only_while_held(self) -> None:
        self.assertEqual(
            capture_while_held([(False, b"before"), (True, b"aa"), (True, b"bb"), (False, b"after")]),
            b"aabb",
        )
        started = threading.Event()
        reads: list[str] = []

        def read(device_id: str) -> bytes:
            reads.append(device_id)
            started.set()
            return b"pcm"

        def _transcribe(audio: bytes) -> str:
            self.assertTrue(audio.startswith(b"pcm"))
            self.assertNotIn(b"after", audio)
            return "heard"

        session = PushToTalk(read, _transcribe)
        session.accept(b"before")
        session.start("bt-mic")
        self.assertTrue(started.wait(1))
        self.assertEqual(session.stop(), "heard")
        self.assertFalse(session.holding)
        count = len(reads)
        session.accept(b"after")
        self.assertGreaterEqual(count, 1)
        self.assertTrue(all(device == "bt-mic" for device in reads))

    def test_wake_word_stays_local_and_is_optional(self) -> None:
        cloud_calls: list[bytes] = []

        def detector(frame: bytes, phrase: str) -> bool:
            self.assertEqual(phrase, "jonathan")
            return frame == b"wake"

        def cloud(audio: bytes) -> str:
            cloud_calls.append(audio)
            return "should not run for the wake frame"

        heard, text = hear_wake_word([b"noise", b"wake", b"utterance"], "jonathan", detector, cloud)
        self.assertTrue(heard)
        self.assertEqual(cloud_calls, [b"utterance"])
        self.assertEqual(text, "should not run for the wake frame")
        missed, empty = hear_wake_word([b"noise"], "jonathan", detector, cloud)
        self.assertFalse(missed)
        self.assertEqual(empty, "")
        self.assertTrue(
            local_phrase_detector(b"clip", "jonathan", transcribe_local=lambda _pcm: "hey jonathan")
        )
        message = format_voice_command("wake off", directory=self.voice, backend=_EmptyBackend())
        self.assertIn("off", message)
        self.assertIn("this machine", message)

    def test_import_does_not_load_optional_audio_packages(self) -> None:
        for name in ("faster_whisper", "sounddevice", "piper"):
            self.assertNotIn(name, sys.modules)


class TestCommandAndDesktop(VoiceTestCase):
    def test_voice_command_and_archive_placeholder(self) -> None:
        self.assertEqual(ARCHIVE_NAME, "voice")
        self.assertTrue(SAMPLE_FILES)
        text = format_voice_command("", directory=self.voice, backend=_EmptyBackend())
        self.assertIn("Speech-to-text: local", text)
        self.assertIn("clawd-codex[voice]", text)
        switched = format_voice_command("stt openai", directory=self.voice, backend=_EmptyBackend())
        self.assertIn("openai", switched)
        self.assertIn("cloud provider", switched)
        context = create_command_context(self.voice)
        ok, result, error = execute_command_sync("voice", "ptt off", context)
        self.assertTrue(ok, error)
        self.assertIn("off", result or "")
        from src.desktop.runtime import _HELP_TEXT

        self.assertIn("/voice", _HELP_TEXT)

    def test_desktop_settings_api(self) -> None:
        server = DesktopServer(runtime=MagicMock(), token="token")
        status, payload = server.handle_api("GET", "/api/voice", {}, None)
        self.assertEqual(status, 200)
        self.assertTrue(payload["settings"]["audio_stays_local"])
        self.assertEqual(payload["settings"]["stt_provider"], "local")
        status, saved = server.handle_api(
            "POST",
            "/api/voice",
            {},
            {"tts_provider": "local", "input_device": "2", "wake_word_enabled": False},
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["settings"]["input_device"], "2")
        self.assertTrue(saved["settings"]["audio_stays_local"])

        class FakeTalk:
            def start(self, device_id: str = "") -> None:
                self.device_id = device_id

            def stop(self) -> str:
                return "from the headset"

        set_controller(FakeTalk())
        status, started = server.handle_api("POST", "/api/voice/ptt", {}, {"action": "start"})
        self.assertEqual(status, 200)
        self.assertTrue(started["holding"])
        self.assertTrue(started["audio_stays_local"])
        status, stopped = server.handle_api("POST", "/api/voice/ptt", {}, {"action": "stop"})
        self.assertEqual(stopped["text"], "from the headset")
        html = Path("src/desktop/web/index.html").read_text(encoding="utf-8")
        script = Path("src/desktop/web/app.js").read_text(encoding="utf-8")
        self.assertIn("voice-stt", html)
        self.assertIn("Hold to talk", html)
        self.assertIn("Local Whisper", html)
        self.assertIn("Local Piper", html)
        self.assertIn("/api/voice", script)

    def test_sources_stay_english_and_do_not_call_blocked_hosts(self) -> None:
        for path in Path("src/voice").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertFalse(any("\u4e00" <= char <= "\u9fff" for char in text), path.name)
            self.assertNotIn("https://hf-mirror", text)
            self.assertNotIn("https://asr.tencentcloudapi.com", text)
            self.assertNotIn("https://api.xiaomimimo.com", text)
        notice = Path("NOTICE").read_text(encoding="utf-8")
        self.assertIn("https://github.com/TencentCloud/Octop", notice)
        self.assertIn("Piper", notice)
        self.assertIn("faster-whisper", notice)


class _EmptyBackend:
    def list_devices(self) -> list[AudioDevice]:
        return []

    def read(self, device_id: str) -> bytes:
        return b""

    def write(self, device_id: str, audio: bytes) -> None:
        return None


class _Backend:
    def __init__(self, devices: list[AudioDevice]) -> None:
        self._devices = devices

    def list_devices(self) -> list[AudioDevice]:
        return list(self._devices)

    def read(self, device_id: str) -> bytes:
        return b""

    def write(self, device_id: str, audio: bytes) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
