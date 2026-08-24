"""Launch the Jonathan Ai desktop window after install."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .app_root import (
    has_electron,
    has_venv,
    probe_app_roots,
    venv_python_exe,
    venv_pythonw_exe,
)


def launch_jonathan_ai(source_dir: Path | None = None) -> dict[str, str]:
    extra = Path(source_dir) if source_dir else None
    root = probe_app_roots(extra=extra) or extra or Path.cwd()
    env = os.environ.copy()
    env["CLAWD_SOURCE_DIR"] = str(root)

    exe = root / "JonathanAi.exe"
    if exe.exists() and (has_venv(root) or has_electron(root)):
        subprocess.Popen([str(exe)], cwd=str(root), env=env)
        return {"launched": str(exe), "kind": "exe", "root": str(root)}

    packaged = root / "packaging" / "windows" / "bin" / "JonathanAi.exe"
    if packaged.exists() and extra is None:
        subprocess.Popen([str(packaged)], cwd=str(root), env=env)
        return {"launched": str(packaged), "kind": "exe", "root": str(root)}

    electron = root / "desktop" / "node_modules" / "electron" / "dist" / (
        "electron.exe" if os.name == "nt" else "electron"
    )
    if electron.exists():
        subprocess.Popen([str(electron), str(root / "desktop")], cwd=str(root / "desktop"), env=env)
        return {"launched": str(electron), "kind": "electron", "root": str(root)}

    python = venv_pythonw_exe(root)
    if not python.exists():
        python = venv_python_exe(root)
    if not python.exists():
        python = Path(shutil.which("pythonw") or shutil.which("python") or shutil.which("python3") or "python3")
    subprocess.Popen([str(python), "-m", "src.cli", "desktop"], cwd=str(root), env=env)
    return {"launched": str(python), "kind": "python", "root": str(root)}
