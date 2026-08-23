"""Locate Python and create the install venv."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .constants import PYTHON_MIN


class PythonNotFoundError(RuntimeError):
    pass


def detect_os() -> dict[str, str]:
    return {
        "system": os.name,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "executable": sys.executable,
    }


def _meets_min(version_text: str) -> bool:
    parts = version_text.strip().split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return False
    return (major, minor) >= PYTHON_MIN


def find_system_python() -> Path:
    """Return a Python 3.10+ executable, preferring the current interpreter."""
    candidates: list[Path] = []
    if sys.version_info >= PYTHON_MIN:
        candidates.append(Path(sys.executable))
    for name in ("python3.12", "python3.11", "python3.10", "python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            result = subprocess.run(
                [str(path), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        if _meets_min(result.stdout):
            return path
    raise PythonNotFoundError(
        "Python 3.10+ is required. Install Python from https://www.python.org/downloads/ "
        "and re-run the wizard."
    )


def venv_python(source_dir: Path) -> Path:
    if os.name == "nt":
        return source_dir / ".venv" / "Scripts" / "python.exe"
    return source_dir / ".venv" / "bin" / "python"


def ensure_venv(source_dir: Path, *, python: Path | None = None) -> Path:
    source_dir = Path(source_dir)
    target = venv_python(source_dir)
    if target.exists():
        return target
    interpreter = Path(python) if python else find_system_python()
    subprocess.run(
        [str(interpreter), "-m", "venv", str(source_dir / ".venv")],
        check=True,
        capture_output=True,
        text=True,
    )
    if not target.exists():
        raise RuntimeError(f"venv was created but {target} is missing")
    return target
