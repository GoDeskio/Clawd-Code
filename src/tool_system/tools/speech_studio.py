"""Local speech transcription and synthesis for conversation attachments."""
from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


_MODELS: dict[tuple[str, str], Any] = {}


def speech_status() -> dict[str, Any]:
    faster = importlib.util.find_spec("faster_whisper") is not None
    return {
        "transcription_ready": faster,
        "transcription_engine": "faster-whisper" if faster else "unavailable",
        "model_download": "first transcription only",
        "synthesis_ready": platform.system() == "Windows" or bool(shutil.which("say") or shutil.which("espeak-ng") or shutil.which("espeak")),
        "synthesis_engine": "Windows System.Speech" if platform.system() == "Windows" else "system voice",
        "privacy": "audio remains local",
    }


def _transcribe(source: Path, model_name: str, language: str, task: str) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ToolInputError("Local speech recognition is not installed. Run Jonathan's dependency repair and retry.") from exc

    try:
        import torch
        use_cuda = bool(torch.cuda.is_available())
    except Exception:
        use_cuda = False
    device = "cuda" if use_cuda else "cpu"
    compute_type = "float16" if use_cuda else "int8"
    key = (model_name, device)
    model = _MODELS.get(key)
    if model is None:
        download_root = Path.home() / ".clawd" / "models" / "whisper"
        download_root.mkdir(parents=True, exist_ok=True)
        model = WhisperModel(model_name, device=device, compute_type=compute_type, download_root=str(download_root))
        _MODELS[key] = model
    kwargs: dict[str, Any] = {"task": task, "vad_filter": True, "beam_size": 5}
    if language and language.lower() != "auto":
        kwargs["language"] = language
    segments, info = model.transcribe(str(source), **kwargs)
    rows = [{"start": round(float(item.start), 3), "end": round(float(item.end), 3), "text": str(item.text).strip()} for item in segments]
    text = " ".join(row["text"] for row in rows if row["text"]).strip()
    return {
        "text": text,
        "segments": rows,
        "language": str(getattr(info, "language", language or "unknown")),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "model": model_name,
        "device": device,
        "engine": "local://faster-whisper",
    }


def _synthesize(text: str, output: Path, voice: str) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Windows":
        env = os.environ.copy()
        env["JONATHAN_SPEECH_TEXT"] = base64.b64encode(text.encode("utf-8")).decode("ascii")
        env["JONATHAN_SPEECH_OUTPUT"] = str(output)
        env["JONATHAN_SPEECH_VOICE"] = voice
        script = (
            "$ErrorActionPreference='Stop';"
            "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:JONATHAN_SPEECH_TEXT));"
            "try{Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "if($env:JONATHAN_SPEECH_VOICE){try{$s.SelectVoice($env:JONATHAN_SPEECH_VOICE)}catch{}};"
            "$s.SetOutputToWaveFile($env:JONATHAN_SPEECH_OUTPUT);$s.Speak($t);$s.Dispose()}"
            "catch{$v=New-Object -ComObject SAPI.SpVoice;$f=New-Object -ComObject SAPI.SpFileStream;"
            "$f.Open($env:JONATHAN_SPEECH_OUTPUT,3,$false);$v.AudioOutputStream=$f;[void]$v.Speak($t);$f.Close()}"
        )
        executable = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"
        completed = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command", script], env=env, capture_output=True, text=True, timeout=180, check=False)
        if completed.returncode != 0:
            output.unlink(missing_ok=True)
            raise ToolInputError((completed.stderr or completed.stdout or "Windows speech synthesis failed").strip())
        engine = "local://windows-system-speech"
    else:
        executable = shutil.which("say") or shutil.which("espeak-ng") or shutil.which("espeak")
        if not executable:
            raise ToolInputError("No local speech synthesizer was found on this device")
        command = [executable]
        if Path(executable).name == "say":
            command += (["-v", voice] if voice else []) + ["-o", str(output), "--data-format=LEI16@22050", text]
        else:
            command += (["-v", voice] if voice else []) + ["-w", str(output), text]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
        if completed.returncode != 0:
            raise ToolInputError((completed.stderr or completed.stdout or "speech synthesis failed").strip())
        engine = f"local://{Path(executable).name}"
    if not output.is_file() or output.stat().st_size == 0:
        raise ToolInputError("Speech synthesis did not create an audio file")
    return engine


class SpeechStudioTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="SpeechStudio",
            description="Transcribe an uploaded audio/voice file locally with a Whisper-family model, or synthesize text to a downloadable WAV using the device's local voice engine. Microphone access is always user initiated.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["status", "transcribe", "synthesize"]},
                    "input": {"type": "string"},
                    "text": {"type": "string"},
                    "output": {"type": "string"},
                    "model": {"type": "string", "enum": ["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"]},
                    "language": {"type": "string"},
                    "task": {"type": "string", "enum": ["transcribe", "translate"]},
                    "voice": {"type": "string"},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        return maybe_ask_for_gated_tool(context, "SpeechStudio", f"Run local speech action '{tool_input.get('action')}'", "Allow local speech processing for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "status":
            return ToolResult(name="SpeechStudio", output=speech_status())
        if action == "transcribe":
            source = context.ensure_allowed_path(str(tool_input.get("input") or ""))
            if not source.is_file():
                raise ToolInputError("input audio file was not found")
            result = _transcribe(source, str(tool_input.get("model") or "tiny"), str(tool_input.get("language") or "auto"), str(tool_input.get("task") or "transcribe"))
            result.update({"ok": True, "input": str(source)})
            return ToolResult(name="SpeechStudio", output=result)
        text = str(tool_input.get("text") or "").strip()
        if not text:
            raise ToolInputError("text is required for speech synthesis")
        output = context.ensure_allowed_path(str(tool_input.get("output") or "media/audio/jonathan-speech.wav"))
        engine = _synthesize(text, output, str(tool_input.get("voice") or ""))
        artifact = context.artifact_publisher(output, output.name) if context.artifact_publisher else {"path": str(output), "name": output.name}
        return ToolResult(name="SpeechStudio", output={"ok": True, "path": str(output), "engine": engine, "artifact": artifact, "artifacts": [artifact]})
