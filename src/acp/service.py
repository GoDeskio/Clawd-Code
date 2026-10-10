"""Run one coding task in a chosen project folder and report changed files."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Callable

from src.acp.protocol import AcpError, AcpProcess
from src.acp.runners import RUNNER_IDS, RUNNER_LABELS, RunnerConfig, load_runners
from src.secret_mask import mask_secrets
from src.security.shell_guard import enforce_shell_command
from src.tool_system.errors import ToolPermissionError

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
_USAGE = (
    "Usage: /acp list | /acp run <runner> <folder> <task>\n"
    "Runners: opencode, claude_code, codex, zed. Enable one in settings first.\n"
    "The project folder and the runner command ask for approval."
)


def snapshot_files(root: Path, *, limit: int = 8000) -> dict[str, tuple[int, int]]:
    """Map relative paths to size and mtime. Skips dependency and VCS trees."""
    found: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                stat = path.stat()
                rel = path.relative_to(root).as_posix()
            except OSError:
                continue
            found[rel] = (int(stat.st_size), int(stat.st_mtime_ns))
            if len(found) >= limit:
                return found
    return found


def changed_files(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    names = [name for name, sig in after.items() if before.get(name) != sig]
    names.extend(name for name in before if name not in after)
    return sorted(set(names))


def resolve_folder(folder: str) -> Path:
    text = folder.strip()
    if not text:
        raise ValueError("project folder is required")
    path = Path(text).expanduser().resolve()
    if path == Path(path.anchor):
        raise ValueError("project folder cannot be the filesystem root")
    if not path.is_dir():
        raise ValueError(f"project folder was not found: {path}")
    return path


def runner_argv(runner: RunnerConfig) -> list[str]:
    if not runner.command.strip():
        raise ValueError("runner command is empty")
    return [runner.command, *runner.args]


def format_result(label: str, text: str, files: list[str]) -> str:
    lines = [label]
    body = text.strip()
    if body:
        lines.append(mask_secrets(body))
    lines.append("")
    if files:
        lines.append("Changed files:")
        lines.extend(f"- {name}" for name in files)
    else:
        lines.append("Changed files: none")
    return "\n".join(lines).strip()


def delegate_task(
    *,
    runner_id: str,
    folder: str,
    task: str,
    directory: Path | None = None,
    user_id: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    timeout_s: float = 120,
    context: object | None = None,
) -> str:
    """Spawn the enabled local runner and return progress plus changed files."""
    name = runner_id.strip()
    if name not in RUNNER_IDS:
        raise ValueError(f"unknown ACP runner: {name}")
    label = RUNNER_LABELS[name]
    runner = load_runners(directory, user_id=user_id)[name]
    if not runner.enabled:
        raise ValueError(f"{label} is not enabled. Turn it on in settings and set its path.")
    project = resolve_folder(folder)
    prompt = task.strip()
    if not prompt:
        raise ValueError("task is required")
    command_line = shlex.join(runner_argv(runner))
    try:
        enforce_shell_command("Acp", command_line, context if context is not None else object())
    except ToolPermissionError as exc:
        raise RuntimeError(str(exc)) from exc
    before = snapshot_files(project)

    def progress(line: str) -> None:
        if on_progress is not None:
            on_progress(mask_secrets(line))

    progress(f"{label} started in {project}")
    try:
        turn = AcpProcess(
            runner_argv(runner),
            project,
            on_progress=progress,
            timeout_s=timeout_s,
        ).run(prompt)
    except (AcpError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc
    after = snapshot_files(project)
    files = changed_files(before, after)
    for reported in turn.paths:
        rel = reported.replace("\\", "/").lstrip("./")
        if rel and rel not in files:
            files.append(rel)
    files = sorted(set(files))
    progress(f"{label} finished")
    return format_result(label, turn.text, files)


def format_acp_command(
    args: str,
    *,
    directory: Path | None = None,
    user_id: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Run `/acp list` or `/acp run` and return text."""
    try:
        parts = shlex.split(args.strip())
    except ValueError as exc:
        return str(exc)
    if not parts or parts[0] == "list":
        return _format_list(directory, user_id=user_id)
    if parts[0] != "run" or len(parts) < 4:
        return _USAGE
    try:
        return delegate_task(
            runner_id=parts[1],
            folder=parts[2],
            task=" ".join(parts[3:]),
            directory=directory,
            user_id=user_id,
            on_progress=on_progress,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        return str(exc)


def _format_list(directory: Path | None, *, user_id: str | None) -> str:
    runners = load_runners(directory, user_id=user_id)
    lines = ["Local ACP runners:"]
    for name in RUNNER_IDS:
        runner = runners[name]
        state = "enabled" if runner.enabled else "disabled"
        lines.append(f"{name}  {RUNNER_LABELS[name]}  {state}  {runner.command_line()}")
    return "\n".join(lines)
