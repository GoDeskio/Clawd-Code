"""First-run install wizard: source, venv, deps, placeholders, verify."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.config import get_default_config, load_config, save_config
from src.providers import PROVIDER_INFO

from .constants import CANONICAL_HTTPS
from .deps import install_blender_dep, install_code_memory_dep, install_desktop_deps, install_drawai_dep, install_ecc_dep, install_fooocus_dep, install_kronos_dep, install_personal_finance_dep, install_procoder_dep, install_python_deps
from .python_env import detect_os, ensure_venv, find_system_python
from .record import write_install_record
from .runtime_process import stop_running_app
from .app_root import discover_existing_install
from .source import current_branch, current_commit, materialize_source
from .verify import verify_agent_session


Progress = Callable[[dict[str, Any]], None]


def write_provider_placeholders() -> None:
    """Ensure ~/.clawd/config.json exists with empty provider slots, no keys."""
    existing = None
    try:
        existing = load_config()
    except Exception:
        existing = None
    if existing and existing.get("providers"):
        # Keep real keys. Only fill missing provider placeholders.
        providers = existing.setdefault("providers", {})
        for name, info in PROVIDER_INFO.items():
            if name not in providers:
                providers[name] = {
                    "api_key": "",
                    "base_url": info["default_base_url"],
                    "default_model": info["default_model"],
                }
        save_config(existing)
        return
    config = get_default_config()
    save_config(config)


def write_launchers(source_dir: Path, python: Path) -> dict[str, str]:
    source_dir = Path(source_dir)
    unix = source_dir / "start-desktop.sh"
    unix.write_text(
        "#!/bin/sh\n"
        f'cd "{source_dir}"\n'
        f'exec "{python}" -m src.cli desktop "$@"\n',
        encoding="utf-8",
    )
    unix.chmod(unix.stat().st_mode | 0o111)
    windows = source_dir / "start-desktop.bat"
    windows.write_text(
        f'@echo off\r\ncd /d "{source_dir}"\r\n"{python}" -m src.cli desktop %*\r\n',
        encoding="utf-8",
    )
    return {"unix": str(unix), "windows": str(windows)}


@dataclass
class WizardJob:
    job_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    done: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None


class InstallWizard:
    def __init__(self) -> None:
        self._jobs: dict[str, WizardJob] = {}
        self._lock = threading.Lock()

    def defaults(self) -> dict[str, Any]:
        return {
            "os": detect_os(),
            "source_dir": str(discover_existing_install()),
            "repo": CANONICAL_HTTPS,
            "from_local": str(Path(__file__).resolve().parents[2]),
        }

    def start(
        self,
        *,
        source_dir: str | Path | None = None,
        from_local: str | Path | None = None,
        skip_desktop_deps: bool = False,
        clone: bool = False,
    ) -> str:
        job = WizardJob(job_id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.job_id] = job
        thread = threading.Thread(
            target=self._run,
            args=(job, source_dir, from_local, skip_desktop_deps, clone),
            daemon=True,
            name=f"clawd-install-{job.job_id[:8]}",
        )
        thread.start()
        return job.job_id

    def drain(self, job_id: str, after: int = 0) -> tuple[list[dict[str, Any]], bool, dict[str, Any] | None, str | None]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"unknown install job: {job_id}")
        with job.condition:
            return list(job.events[after:]), job.done, job.result, job.error

    def run_sync(
        self,
        *,
        source_dir: str | Path | None = None,
        from_local: str | Path | None = None,
        skip_desktop_deps: bool = False,
        clone: bool = False,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        job = WizardJob(job_id="sync")
        if progress:
            def _hook(event: dict[str, Any]) -> None:
                progress(event)
            orig_emit = self._emit

            def emit(j: WizardJob, event: dict[str, Any]) -> None:
                orig_emit(j, event)
                _hook(event)

            self._emit = emit  # type: ignore[method-assign]
        try:
            self._run(job, source_dir, from_local, skip_desktop_deps, clone)
        finally:
            if progress:
                self._emit = orig_emit  # type: ignore[method-assign]
        if job.error:
            raise RuntimeError(job.error)
        return job.result or {}

    def _emit(self, job: WizardJob, event: dict[str, Any]) -> None:
        with job.condition:
            job.events.append(event)
            job.condition.notify_all()

    def _run(
        self,
        job: WizardJob,
        source_dir: str | Path | None,
        from_local: str | Path | None,
        skip_desktop_deps: bool,
        clone: bool,
    ) -> None:
        restart_after_install = False
        dest = Path(source_dir).expanduser() if source_dir else discover_existing_install()
        try:
            process_state = stop_running_app(dest)
            restart_after_install = bool(process_state.get("was_running"))
            if restart_after_install and not process_state.get("stopped"):
                raise RuntimeError("Jonathan Ai is running and could not be stopped for an in-place upgrade")
            if restart_after_install:
                self._emit(job, {"type": "step", "id": "restart", "message": "Stopped the running app for an in-place upgrade"})
            self._emit(job, {"type": "step", "id": "os", "message": f"Detected {detect_os()['platform']}"})
            self._emit(job, {"type": "step", "id": "python", "message": "Locating Python 3.10+"})
            python = find_system_python()
            self._emit(job, {"type": "step", "id": "python", "message": f"Using {python}"})

            local = None if clone else (Path(from_local) if from_local else Path(__file__).resolve().parents[2])
            if local is not None and not (local / "src" / "cli.py").exists():
                local = None
            self._emit(job, {
                "type": "step",
                "id": "source",
                "message": f"Saving source to {dest} from {'local tree' if local else CANONICAL_HTTPS}",
            })
            tree = materialize_source(dest, from_local=local, retry=3)
            self._emit(job, {"type": "step", "id": "source", "message": f"Source ready at {tree}"})

            self._emit(job, {"type": "step", "id": "venv", "message": "Creating virtualenv"})
            venv = ensure_venv(tree, python=python)
            self._emit(job, {"type": "step", "id": "venv", "message": f"venv python: {venv}"})

            def pip_progress(message: str) -> None:
                self._emit(job, {"type": "step", "id": "deps", "message": message})

            install_python_deps(venv, tree, retry=3, progress=pip_progress)
            blender_status = install_blender_dep(venv, tree, progress=pip_progress)
            fooocus_status = install_fooocus_dep(tree, progress=pip_progress)
            desktop_status = "skipped"
            if not skip_desktop_deps:
                desktop_status = install_desktop_deps(tree, retry=3, progress=pip_progress)
                if desktop_status == "failed":
                    raise RuntimeError("Electron desktop dependencies could not be installed")

            self._emit(job, {"type": "step", "id": "config", "message": "Writing provider placeholders (no API keys)"})
            write_provider_placeholders()
            from src.skills.library import ensure_learning_skill

            ensure_learning_skill(source_dir=tree)
            self._emit(job, {"type": "step", "id": "skills", "message": f"Shared skill library ready at {tree / 'Skills'}"})
            ecc_status = install_ecc_dep(tree, progress=pip_progress)
            kronos_status = install_kronos_dep(tree, progress=pip_progress)
            personal_finance_status = install_personal_finance_dep(tree, progress=pip_progress)
            code_memory_status = install_code_memory_dep(tree, progress=pip_progress)
            procoder_status = install_procoder_dep(tree, progress=pip_progress)
            drawai_status = install_drawai_dep(tree, progress=pip_progress)

            self._emit(job, {"type": "step", "id": "verify", "message": "Verifying the agent can start a session"})
            verification = verify_agent_session(tree, python_path=venv)

            launchers = write_launchers(tree, venv)
            commit = current_commit(tree)
            branch = current_branch(tree)
            write_install_record(source_dir=tree, venv_python=venv, commit=commit, branch=branch)

            result = {
                "ok": True,
                "source_dir": str(tree),
                "venv_python": str(venv),
                "repo": CANONICAL_HTTPS,
                "desktop_deps": desktop_status,
                "blender": blender_status,
                "fooocus": fooocus_status,
                "ecc": ecc_status,
                "kronos": kronos_status,
                "personal_finance": personal_finance_status,
                "code_memory": code_memory_status,
                "procoder": procoder_status,
                "drawai": drawai_status,
                "launchers": launchers,
                "verification": verification,
                "commit": commit,
                "branch": branch,
                "restart_required": restart_after_install,
            }
            job.result = result
            self._emit(job, {"type": "done", **result})
            with job.condition:
                job.done = True
                job.condition.notify_all()
        except Exception as exc:
            if restart_after_install:
                try:
                    from .launch import launch_jonathan_ai

                    launch_jonathan_ai(dest)
                except Exception:
                    pass
            job.error = str(exc)
            self._emit(job, {"type": "error", "error": str(exc)})
            with job.condition:
                job.done = True
                job.condition.notify_all()
