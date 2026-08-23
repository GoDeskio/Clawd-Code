"""Locate the Jonathan Ai app folder on disk.

The Windows launcher and Setup must find %USERPROFILE%\\Jonathan\\Jonathan-Ai
even when JonathanAi.exe was left in the parent Jonathan folder.
"""

from __future__ import annotations

import os
from pathlib import Path

from .constants import JONATHAN_FOLDER_NAME, SOURCE_FOLDER_NAME
from .source import default_source_dir


def _electron_exe(root: Path) -> Path:
    name = "electron.exe" if os.name == "nt" else "electron"
    return root / "desktop" / "node_modules" / "electron" / "dist" / name


def venv_python_exe(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def venv_pythonw_exe(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "pythonw.exe"
    return root / ".venv" / "bin" / "python"


def has_cli(root: Path) -> bool:
    return (Path(root) / "src" / "cli.py").is_file()


def has_venv(root: Path) -> bool:
    root = Path(root)
    return any(
        path.is_file()
        for path in (
            root / ".venv" / "Scripts" / "python.exe",
            root / ".venv" / "Scripts" / "pythonw.exe",
            root / ".venv" / "bin" / "python",
            root / ".venv" / "bin" / "pythonw",
        )
    )


def has_electron(root: Path) -> bool:
    return _electron_exe(Path(root)).is_file()


def is_app_root(root: str | Path | None) -> bool:
    """True when the folder has src\\cli.py and a venv or Electron binary."""
    if not root:
        return False
    path = Path(root).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return False
    if not has_cli(path):
        return False
    return has_venv(path) or has_electron(path)


def default_jonathan_ai_dir(home: Path | None = None) -> Path:
    return default_source_dir(home=home)


def existing_install_candidates(*, home: Path | None = None) -> list[Path]:
    """Folders Setup should reuse instead of creating a parallel install."""
    root = Path(home) if home is not None else Path.home()
    items: list[Path] = []
    try:
        from .record import read_install_record

        record = read_install_record(home=root)
        recorded = str((record or {}).get("source_dir") or "").strip()
        if recorded:
            items.append(Path(recorded).expanduser())
    except Exception:
        pass
    items.extend(
        [
            root / JONATHAN_FOLDER_NAME / SOURCE_FOLDER_NAME,
            root / JONATHAN_FOLDER_NAME / "Clawd-Code",
            root / "Clawd-Code",
        ]
    )
    seen: set[str] = set()
    unique: list[Path] = []
    for item in items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def discover_existing_install(*, home: Path | None = None) -> Path:
    """Return the existing Jonathan-Ai / Clawd-Code tree, or the default path."""
    for path in existing_install_candidates(home=home):
        if has_cli(path):
            return path
    return default_jonathan_ai_dir(home=home)


def probe_app_roots(
    *,
    env_dir: str | Path | None = None,
    exe_dir: str | Path | None = None,
    home: Path | None = None,
    cwd: str | Path | None = None,
    extra: str | Path | None = None,
) -> Path | None:
    """First valid root: extra, CLAWD_SOURCE_DIR, exe dir, Jonathan-Ai, cwd."""
    root_home = Path(home) if home is not None else Path.home()
    env_value = env_dir if env_dir is not None else os.environ.get("CLAWD_SOURCE_DIR")
    cwd_value = Path(cwd) if cwd is not None else Path.cwd()
    candidates = [
        extra,
        env_value,
        exe_dir,
        root_home / JONATHAN_FOLDER_NAME / SOURCE_FOLDER_NAME,
        cwd_value,
    ]
    seen: set[str] = set()
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if is_app_root(path):
            return path.resolve()
    return None


def leftover_parent_exes(source_dir: Path) -> list[Path]:
    """JonathanAi.exe / Setup.exe wrongly left in the parent Jonathan folder."""
    source_dir = Path(source_dir)
    parent = source_dir.parent
    if source_dir.name != SOURCE_FOLDER_NAME or parent.name != JONATHAN_FOLDER_NAME:
        return []
    return [
        parent / "JonathanAi.exe",
        parent / "JonathanAi-Setup.exe",
    ]
