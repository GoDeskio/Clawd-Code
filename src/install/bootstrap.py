"""Repair venv, pip, and optional Electron on first desktop launch.

Setup already installs these. This path covers a pull of new code, a
broken venv, or a machine that never finished Setup. Electron is optional.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .app_root import discover_existing_install
from .deps import install_blender_dep, install_code_memory_dep, install_desktop_deps, install_drawai_dep, install_ecc_dep, install_fooocus_dep, install_kronos_dep, install_personal_finance_dep, install_procoder_dep, install_python_deps
from .python_env import ensure_venv, venv_is_usable
from .record import resolve_source_dir, write_install_record
from .source import current_branch, current_commit
from src.version import get_version

CRITICAL_IMPORT = "import anthropic, openai, rich, dotenv, prompt_toolkit, tiktoken, PIL, cv2, rapidocr_onnxruntime, trimesh, psutil, yfinance, pandas, pypdf, docx, openpyxl, pptx, pyautogui"
# The shipped native launcher was last compiled with this readiness marker.
# Setup still writes the current marker; this compatibility marker prevents a
# successful fresh install from repeating the same repair on every launch.
LAUNCHER_COMPAT_VERSION = "0.4.6"


def runtime_ready_marker(source_dir: str | Path, version: str | None = None) -> Path:
    """Marker used by the native/Electron launchers to skip repeat repairs."""
    release = str(version or get_version()).strip()
    return Path(source_dir).expanduser().resolve() / f".jonathan-ai-runtime-{release}.ready"


def write_runtime_ready_marker(source_dir: str | Path, result: dict[str, Any]) -> Path | None:
    if not result.get("ok"):
        return None
    root = Path(source_dir).expanduser().resolve()
    marker = runtime_ready_marker(root)
    marker.write_text(json.dumps({
        "version": get_version(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": str(result.get("venv_python") or ""),
    }, indent=2), encoding="utf-8")
    compatibility = runtime_ready_marker(root, LAUNCHER_COMPAT_VERSION)
    if compatibility != marker:
        compatibility.write_text(marker.read_text(encoding="utf-8"), encoding="utf-8")
    return marker


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
    skip_blender: bool = False,
    skip_fooocus: bool = False,
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
    desktop_status = "skipped" if skip_desktop else "present"
    if not skip_desktop and not _electron_present(root):
        try:
            desktop_status = install_desktop_deps(root, retry=2, progress=log)
        except Exception as exc:
            desktop_status = "failed"
            log(f"Electron optional install failed: {exc}")
    blender_status = "skipped"
    if not skip_blender:
        try:
            blender_status = install_blender_dep(python, root, progress=log)
        except Exception as exc:
            blender_status = "failed"
            log(f"Required Blender install failed: {exc}")
    fooocus_status = "skipped"
    if not skip_fooocus:
        try:
            fooocus_status = install_fooocus_dep(root, progress=log)
        except Exception as exc:
            fooocus_status = "failed"
            log(f"Required local image-engine install failed: {exc}")
    kronos_status = install_kronos_dep(root, progress=log)
    personal_finance_status = install_personal_finance_dep(root, progress=log)
    code_memory_status = install_code_memory_dep(root, progress=log)
    procoder_status = install_procoder_dep(root, progress=log)
    drawai_status = install_drawai_dep(root, progress=log)
    ecc_status = install_ecc_dep(root, progress=log)
    try:
        write_install_record(
            source_dir=root,
            venv_python=python,
            commit=current_commit(root),
            branch=current_branch(root),
        )
    except Exception:
        pass
    result = {
        "ok": venv_is_usable(root) and pip_status != "failed" and blender_status != "failed" and fooocus_status != "failed" and desktop_status != "failed",
        "source_dir": str(root),
        "venv_python": str(python),
        "pip": pip_status,
        "desktop_deps": desktop_status,
        "blender": blender_status,
        "fooocus": fooocus_status,
        "kronos": kronos_status,
        "personal_finance": personal_finance_status,
        "code_memory": code_memory_status,
        "procoder": procoder_status,
        "drawai": drawai_status,
        "ecc": ecc_status,
        "notes": notes,
    }
    write_runtime_ready_marker(root, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair Jonathan Ai runtime dependencies")
    parser.add_argument("--source-dir", default=None)
    parser.add_argument("--skip-desktop-deps", action="store_true")
    parser.add_argument("--skip-blender", action="store_true")
    parser.add_argument("--skip-fooocus", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = ensure_runtime_deps(
            args.source_dir,
            skip_desktop=args.skip_desktop_deps,
            skip_blender=args.skip_blender,
            skip_fooocus=args.skip_fooocus,
            progress=lambda message: print(message, flush=True),
        )
    except Exception as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print(f"bootstrap pip={result['pip']} electron={result['desktop_deps']} blender={result['blender']} fooocus={result['fooocus']} ecc={result['ecc']}", flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
