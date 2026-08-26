"""Install Python and optional desktop-shell dependencies with retries."""

from __future__ import annotations

import os
import shutil
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


def install_fooocus_dep(
    source_dir: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Prepare Jonathan's native local Diffusers image engine."""
    integration = source_dir / "src" / "integrations" / "fooocus.py"
    if not integration.is_file():
        return "skipped"
    from src.integrations.fooocus import FooocusManager

    manager = FooocusManager(source_dir)
    status = manager.install(progress=progress)
    if not status.get("source_ready") or not status.get("dependencies_ready"):
        raise RuntimeError("Local image engine install completed without a usable runtime")
    return "ready"


def install_ecc_dep(
    source_dir: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Synchronize and audit the managed ECC catalog during setup.

    ECC is an optional knowledge pack rather than a runtime prerequisite, so
    an offline installer remains usable and the desktop can retry later.
    """
    if progress:
        progress("Synchronizing the audited ECC skills and agent catalog")
    try:
        from src.integrations.ecc import import_catalog, sync

        sync(source_dir)
        result = import_catalog(source_dir)
    except Exception as exc:
        if progress:
            progress(f"ECC catalog deferred (retry from Skills library): {exc}")
        return "deferred"
    if progress:
        progress(
            f"ECC ready: {len(result.get('imported_skills') or [])} skills, "
            f"{len(result.get('imported_agents') or [])} agent templates"
        )
    return "ready"


def install_kronos_dep(
    source_dir: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Install the local Kronos research-forecasting engine when online."""
    if progress:
        progress("Preparing the Kronos financial-market forecasting engine")
    try:
        from src.integrations.kronos import KronosManager

        result = KronosManager(source_dir).install(progress=progress)
    except Exception as exc:
        if progress:
            progress(f"Kronos deferred (retry from Business & finance): {exc}")
        return "deferred"
    return "ready" if result.get("source_ready") and result.get("runtime_ready") else "deferred"


def install_personal_finance_dep(
    source_dir: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Sync the optional isolated finance service without starting containers."""
    if progress:
        progress("Preparing the optional private personal-finance service")
    try:
        from src.integrations.securo import SecuroManager

        result = SecuroManager(source_dir).sync(progress)
    except Exception as exc:
        if progress:
            progress(f"Personal finance service deferred (retry from Connect tools): {exc}")
        return "deferred"
    return "ready" if result.get("source_ready") else "deferred"


def install_code_memory_dep(
    source_dir: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Install the optional local code graph without adding Claude-specific hooks."""
    if progress:
        progress("Preparing the local code-memory and symbol-graph engine")
    try:
        from src.integrations.claude_db import ClaudeDbManager

        result = ClaudeDbManager(source_dir).install(progress)
    except Exception as exc:
        if progress:
            progress(f"Code-memory engine deferred (retry from Connect tools): {exc}")
        return "deferred"
    return "ready" if result.get("runtime_ready") else "deferred"


def install_procoder_dep(source_dir: Path, *, progress: Progress | None = None) -> str:
    """Verify the optional standalone engineering gate and its upstream checksum."""
    if progress:
        progress("Preparing the Procoder engineering-quality controller")
    try:
        from src.integrations.procoder import ProcoderManager

        result = ProcoderManager(source_dir).install(progress)
    except Exception as exc:
        if progress:
            progress(f"Procoder deferred (retry from Connect tools): {exc}")
        return "deferred"
    return "ready" if result.get("runtime_ready") and result.get("checksum_verified") else "deferred"


def install_drawai_dep(source_dir: Path, *, progress: Progress | None = None) -> str:
    """Install DrawAI code dependencies; large optional models download on first use."""
    if progress:
        progress("Preparing DrawAI editable SVG/PPTX dependencies")
    try:
        from src.integrations.drawai import DrawAiManager

        result = DrawAiManager(source_dir).install(models=False, progress=progress)
    except Exception as exc:
        if progress:
            progress(f"DrawAI deferred (retry from Image Studio): {exc}")
        return "deferred"
    return "ready" if result.get("dependencies_ready") else "deferred"


def install_desktop_deps(
    source_dir: Path,
    *,
    retry: int = 3,
    progress: Progress | None = None,
) -> str:
    """Install Electron deps, bootstrapping Node.js LTS on Windows when needed."""
    desktop = source_dir / "desktop"
    if not (desktop / "package.json").exists():
        return "skipped"
    npm = shutil.which("npm")
    if not npm and os.name == "nt":
        winget = shutil.which("winget")
        if winget:
            if progress:
                progress("Node.js is missing; installing Node.js LTS")
            try:
                _run([
                    winget,
                    "install",
                    "--id",
                    "OpenJS.NodeJS.LTS",
                    "-e",
                    "--source",
                    "winget",
                    "--silent",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ])
            except RuntimeError as exc:
                if progress:
                    progress(f"Node.js automatic install failed: {exc}")
            candidates = [
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npm.cmd",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "npm.cmd",
            ]
            npm = next((str(path) for path in candidates if path.exists()), None)
    if not npm:
        if progress:
            progress("npm is unavailable; Electron desktop dependencies could not be installed")
        return "failed"
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
    if progress:
        progress("Electron install skipped after retries — browser UI still works")
    return "failed"


def install_blender_dep(
    python: Path,
    source_dir: Path,
    *,
    progress: Progress | None = None,
) -> str:
    """Ensure the full Blender engine is present, including portable fallback."""
    if progress:
        progress("Checking Blender 3D engine")
    code = (
        "from pathlib import Path; "
        "from src.tool_system.context import ToolContext; "
        "from src.tool_system.tools.three_d_studio import ThreeDStudioTool; "
        "result=ThreeDStudioTool().run({'action':'install_blender','timeout':1800}, ToolContext(workspace_root=Path.cwd())); "
        "print(result.output); "
        "raise SystemExit(1 if result.is_error else 0)"
    )
    _run([str(python), "-c", code], cwd=source_dir)
    if progress:
        progress("Blender 3D engine is ready")
    return "ready"
