"""Launch the Jonathan Ai desktop window after install."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def launch_jonathan_ai(source_dir: Path) -> dict[str, str]:
    root = Path(source_dir)
    env = os.environ.copy()
    env["CLAWD_SOURCE_DIR"] = str(root)

    exe = root / "JonathanAi.exe"
    if exe.exists():
        subprocess.Popen([str(exe)], cwd=str(root), env=env)
        return {"launched": str(exe), "kind": "exe"}

    packaged = root / "packaging" / "windows" / "bin" / "JonathanAi.exe"
    if packaged.exists():
        subprocess.Popen([str(packaged)], cwd=str(root), env=env)
        return {"launched": str(packaged), "kind": "exe"}

    electron = root / "desktop" / "node_modules" / "electron" / "dist" / (
        "electron.exe" if os.name == "nt" else "electron"
    )
    if electron.exists():
        subprocess.Popen([str(electron), str(root / "desktop")], cwd=str(root / "desktop"), env=env)
        return {"launched": str(electron), "kind": "electron"}

    python = root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "pythonw.exe" if os.name == "nt" else "python"
    )
    if not python.exists():
        python = Path(shutil.which("pythonw") or shutil.which("python") or shutil.which("python3") or "python3")
    subprocess.Popen([str(python), "-m", "src.cli", "desktop"], cwd=str(root), env=env)
    return {"launched": str(python), "kind": "python"}
