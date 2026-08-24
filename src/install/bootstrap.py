"""Repair venv, pip, and optional Electron on first desktop launch.

Setup already installs these. This path covers a pull of new code, a
broken venv, or a machine that never finished Setup. Electron is optional.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .app_root import discover_existing_install
from .deps import install_desktop_deps, install_python_deps
from .python_env import ensure_venv, venv_is_usable
from .record import resolve_source_dir, write_install_record
from .source import current_branch, current_commit

CRITICAL_IMPORT = "import anthropic, openai, rich, dotenv, prompt_toolkit"


def resolve_source(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("CLAWD_SOURCE_DIR")
    if env:
        candidates.append(Path(env).expanduser())
    recorded = resolve_source_dir()
    if recorded:
        candidates.append(recorded)
    candidates.append(Path.cwd())
    candidates.append(discover_existing_install())
    for raw in candidates:
        path = Path(raw).expanduser()
        if (path / "src" / "cli.py").is_file():
            return path.resolve()
    return discover_existing_install()


def _imports_ok(python: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-c", CRITICAL_IMPORT],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _electron_present(source_dir: Path) -> bool:
    if os.name == "nt":
        exe = source_dir / "desktop" / "node_modules" / "electron" / "dist" / "electron.exe"
    else:
        exe = source_dir / "desktop" / "node_modules" / "electron" / "dist" / "electron"
    return exe.is_file()


def ensure_runtime_deps(
    source_dir: str | Path | None = None,
    *,
    skip_desktop: bool = False,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Create/repair the venv and install missing packages. Never raises for Electron."""
    notes: list[str] = []

    def log(message: str) -> None:
        notes.append(message)
        if progress:
            progress(message)

    root = resolve_source(source_dir)
    log(f"source={root}")
    python = ensure_venv(root)
    log(f"venv={python}")
    pip_status = "ok"
    if not _imports_ok(python):
        log("Missing Python packages — installing requirements")
        install_python_deps(python, root, retry=3, progress=log)
        pip_status = "installed"
        if not _imports_ok(python):
            pip_status = "failed"
            log("Python packages still missing after pip")
    desktop_status = "skipped"
    if not skip_desktop and not _electron_present(root):
        try:
            desktop_status = install_desktop_deps(root, retry=2, progress=log)
        except Exception as exc:
            desktop_status = "failed"
            log(f"Electron optional install failed: {exc}")
    try:
        write_install_record(
            source_dir=root,
            venv_python=python,
            commit=current_commit(root),
            branch=current_branch(root),
        )
    except Exception:
        pass
    return {
        "ok": venv_is_usable(root) and pip_status != "failed",
        "source_dir": str(root),
        "venv_python": str(python),
        "pip": pip_status,
        "desktop_deps": desktop_status,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair Jonathan Ai runtime dependencies")
    parser.add_argument("--source-dir", default=None)
    parser.add_argument("--skip-desktop-deps", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = ensure_runtime_deps(
            args.source_dir,
            skip_desktop=args.skip_desktop_deps,
            progress=lambda message: print(message, flush=True),
        )
    except Exception as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print(f"bootstrap pip={result['pip']} electron={result['desktop_deps']}", flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
