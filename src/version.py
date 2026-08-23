"""Single product version for Jonathan Ai."""

from __future__ import annotations

from pathlib import Path

DEFAULT_VERSION = "0.2.7"


def get_version() -> str:
    here = Path(__file__).resolve()
    candidates = (
        here.parents[1] / "VERSION",
        here.parent / "VERSION",
    )
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text.splitlines()[0].strip()
    return DEFAULT_VERSION
