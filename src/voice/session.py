"""Push-to-talk capture and an optional local wake word.

The microphone is read only while push-to-talk is held, or while the user
has turned the wake word on. Wake-word audio is scored on this machine and
is never handed to a cloud transport.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .models import VoiceError

FrameReader = Callable[[str], bytes]
WakeDetector = Callable[[bytes, str], bool]
Transcriber = Callable[[bytes], str]


class PushToTalk:
    """Record from ``read_frame`` only while the button is held."""

    def __init__(self, read_frame: FrameReader, transcribe: Transcriber) -> None:
        self._read_frame = read_frame
        self._transcribe = transcribe
        self._lock = threading.Lock()
        self._holding = False
        self._device_id = ""
        self._frames: list[bytes] = []
        self._thread: threading.Thread | None = None
        self._error = ""

    @property
    def holding(self) -> bool:
        with self._lock:
            return self._holding

    def start(self, device_id: str = "") -> None:
        with self._lock:
            self._frames = []
            self._error = ""
            self._device_id = device_id
            self._holding = True
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, name="jonathan-ptt", daemon=True)
            self._thread.start()

    def accept(self, frame: bytes) -> None:
        """Keep a frame only when push-to-talk is held."""
        if not frame:
            return
        with self._lock:
            if self._holding:
                self._frames.append(frame)

    def stop(self) -> str:
        thread = None
        with self._lock:
            self._holding = False
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        with self._lock:
            audio = b"".join(self._frames)
            error = self._error
            self._frames = []
        if error:
            raise VoiceError(error)
        if not audio:
            return ""
        return self._transcribe(audio)

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._holding:
                    return
                device_id = self._device_id
            try:
                frame = self._read_frame(device_id)
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
                    self._holding = False
                return
            with self._lock:
                holding = self._holding
                if holding and frame:
                    self._frames.append(frame)
            if not holding:
                return
            time.sleep(0.01)


def capture_while_held(frames: list[tuple[bool, bytes]]) -> bytes:
    """Join frames whose hold flag is true. Released frames are dropped."""
    chunks: list[bytes] = []
    for held, frame in frames:
        if held and frame:
            chunks.append(frame)
    return b"".join(chunks)


def hear_wake_word(
    frames: list[bytes],
    phrase: str,
    detector: WakeDetector,
    transcribe: Transcriber,
) -> tuple[bool, str]:
    """Score each frame locally. Only audio after the phrase is transcribed."""
    heard_at = None
    for index, frame in enumerate(frames):
        if detector(frame, phrase):
            heard_at = index
            break
    if heard_at is None:
        return False, ""
    utterance = b"".join(frames[heard_at + 1 :])
    if not utterance:
        return True, ""
    return True, transcribe(utterance)


def local_phrase_detector(pcm: bytes, phrase: str, *, transcribe_local: Transcriber) -> bool:
    """Match a wake phrase with the local transcriber. No cloud transport is available."""
    if not pcm or not phrase:
        return False
    text = transcribe_local(pcm)
    return phrase.casefold() in text.casefold()
