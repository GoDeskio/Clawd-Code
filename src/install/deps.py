"""Install Python and optional desktop-shell dependencies with retries."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{' '.join(cmd)} failed: {detail[-400:]}")


def install_python_deps(
    python: Path,
    source_dir: Path,
    *,
    retry: int = 3,
    progress: Progress | None = None,
) -> None:
    req = source_dir / "requirements.txt"
    last: Exception | None = None
    for attempt in range(1, retry + 1):
        try:
            if progress:
                progress(f"Installing Python packages (attempt {attempt}/{retry})")
            _run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=source_dir)
            if req.exists():
                _run([str(python), "-m", "pip", "install", "-r", str(req)], cwd=source_dir)
            else:
                _run([str(python), "-m", "pip", "install", "-e", str(source_dir)], cwd=source_dir)
            extras = source_dir / "pyproject.toml"
            if extras.exists():
                _run([str(python), "-m", "pip", "install", "-e", str(source_dir)], cwd=source_dir)
            return
        except Exception as exc:
            last = exc
            if progress:
                progress(f"Python dependency install failed: {exc}")
    raise RuntimeError(f"Python dependency install failed after {retry} attempts: {last}")


def install_desktop_deps(
    source_dir: Path,
    *,
    retry: int = 3,
    progress: Progress | None = None,
) -> str:
    """Install Electron deps when npm is available. Optional on Linux CI."""
    import shutil

    desktop = source_dir / "desktop"
    if not (desktop / "package.json").exists():
        return "skipped"
    npm = shutil.which("npm")
    if not npm:
        if progress:
            progress("npm not found — Electron shell skipped; browser UI still works")
        return "skipped"
    last: Exception | None = None
    for attempt in range(1, retry + 1):
        try:
            if progress:
                progress(f"Installing desktop shell packages (attempt {attempt}/{retry})")
            _run([npm, "install"], cwd=desktop)
            return "installed"
        except Exception as exc:
            last = exc
            if progress:
                progress(f"npm install failed: {exc}")
    raise RuntimeError(f"desktop dependency install failed after {retry} attempts: {last}")
