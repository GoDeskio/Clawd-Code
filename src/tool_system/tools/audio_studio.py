"""Jonathan-native procedural WAV generation and editing."""
from __future__ import annotations

import hashlib
import math
import wave
from pathlib import Path
from typing import Any

import numpy as np

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels, width, rate, frames = handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()
        if width != 2:
            raise ToolInputError("AudioStudio currently edits 16-bit PCM WAV files")
        data = np.frombuffer(handle.readframes(frames), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _write_wav(path: Path, data: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(pcm.tobytes())


def _procedural(prompt: str, duration: float, rate: int = 44100) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(prompt.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed); lower = prompt.lower()
    bpm = 72 if any(word in lower for word in ("calm", "ambient", "slow")) else 118 if any(word in lower for word in ("dance", "fast", "energy")) else 94
    root = 48 + seed % 12; scale = [0, 2, 3, 5, 7, 10] if any(word in lower for word in ("minor", "dark", "moody")) else [0, 2, 4, 7, 9]
    count = max(1, int(duration * rate)); output = np.zeros(count, dtype=np.float32); beat = 60.0 / bpm
    step = beat / 2; notes = int(math.ceil(duration / step))
    for index in range(notes):
        start = int(index * step * rate); end = min(count, int((index + 1) * step * rate)); size = end - start
        if size <= 0: continue
        midi = root + scale[(index + int(rng.integers(0, len(scale)))) % len(scale)] + (12 if index % 8 in {6, 7} else 0)
        freq = 440.0 * 2 ** ((midi - 69) / 12); t = np.arange(size, dtype=np.float32) / rate
        attack = np.minimum(1.0, t / .018); release = np.minimum(1.0, (size / rate - t) / .09); env = np.maximum(0, attack * release)
        tone = np.sin(2 * np.pi * freq * t) + .28 * np.sin(4 * np.pi * freq * t)
        output[start:end] += .20 * tone * env
    # Lightweight kick and brushed-noise rhythm.
    for index in range(int(duration / beat) + 1):
        start = int(index * beat * rate); size = min(count - start, int(.18 * rate))
        if size <= 0: continue
        t = np.arange(size, dtype=np.float32) / rate
        output[start:start + size] += .32 * np.sin(2 * np.pi * (72 - 35 * t) * t) * np.exp(-18 * t)
        if index % 2:
            output[start:start + size] += .035 * rng.normal(size=size).astype(np.float32) * np.exp(-24 * t)
    peak = float(np.max(np.abs(output))) or 1.0
    return output * min(1.0, .92 / peak)


class AudioStudioTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(name="AudioStudio", description="Generate deterministic original instrumental WAV beds and trim, normalize, or mix local 16-bit WAV files. Outputs are downloadable and require no account, cloud API, or external repository.", input_schema={
            "type":"object", "additionalProperties":False,
            "properties":{
                "action":{"type":"string","enum":["generate","trim","normalize","mix"]},
                "prompt":{"type":"string"}, "input":{"type":"string"}, "inputs":{"type":"array","items":{"type":"string"}},
                "output":{"type":"string"}, "duration":{"type":"number","minimum":1,"maximum":300},
                "start":{"type":"number","minimum":0}, "end":{"type":"number","minimum":0},
            }, "required":["action"]}, is_destructive=True, max_result_size_chars=20000, strict=True)

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        return maybe_ask_for_gated_tool(context,"AudioStudio",f"Create or edit audio with action '{tool_input.get('action')}'","Allow audio file creation for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action=str(tool_input["action"]); output=context.ensure_allowed_path(str(tool_input.get("output") or f"media/audio/jonathan-{action}.wav"))
        if action == "generate":
            prompt=str(tool_input.get("prompt") or "warm optimistic instrumental")
            data=_procedural(prompt,max(1.0,min(float(tool_input.get("duration") or 12),300))); rate=44100
        elif action in {"trim","normalize"}:
            source=context.ensure_allowed_path(str(tool_input.get("input") or ""))
            if not source.is_file(): raise ToolInputError("input WAV file was not found")
            data,rate=_read_wav(source)
            if action == "trim":
                start=max(0.0,float(tool_input.get("start") or 0)); end=float(tool_input.get("end") or len(data)/rate)
                if end <= start: raise ToolInputError("end must be greater than start")
                data=data[int(start*rate):min(len(data),int(end*rate))]
            else:
                peak=float(np.max(np.abs(data))) if len(data) else 0
                if peak: data=data*(.95/peak)
        else:
            paths=[context.ensure_allowed_path(str(item)) for item in tool_input.get("inputs") or []]
            if len(paths)<2 or any(not path.is_file() for path in paths): raise ToolInputError("mix requires at least two existing WAV files")
            tracks=[]; rates=[]
            for path in paths: samples,rate=_read_wav(path); tracks.append(samples); rates.append(rate)
            if len(set(rates)) != 1: raise ToolInputError("mix inputs must use the same sample rate")
            rate=rates[0]; size=max(map(len,tracks)); data=np.zeros(size,dtype=np.float32)
            for track in tracks: data[:len(track)] += track/len(tracks)
        _write_wav(output,data,rate)
        artifact=context.artifact_publisher(output,output.name) if context.artifact_publisher else {"path":str(output),"name":output.name}
        return ToolResult(name="AudioStudio",output={"ok":True,"action":action,"path":str(output),"duration_seconds":round(len(data)/rate,3),"sample_rate":rate,"artifact":artifact,"artifacts":[artifact],"engine":"internal://jonathan/audio-studio"})
