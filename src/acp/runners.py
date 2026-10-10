"""Per-user ACP runner settings. Runners are disabled until enabled here."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from src.agent.memory import current_user_id

RUNNER_IDS = ("opencode", "claude_code", "codex", "zed")

RUNNER_LABELS = {
    "opencode": "OpenCode",
    "claude_code": "Claude Code",
    "codex": "Codex",
    "zed": "Zed",
}

# Local program names. The settings panel replaces these with a real path.
# Nothing is downloaded, and npx is not the default.
_DEFAULTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "opencode": ("opencode", ("acp",)),
    "claude_code": ("claude-agent-acp", ()),
    "codex": ("codex-acp", ()),
    "zed": ("zed", ("acp",)),
}


@dataclass
class RunnerConfig:
    enabled: bool = False
    command: str = ""
    args: tuple[str, ...] = ()

    def command_line(self) -> str:
        return shlex.join([self.command, *self.args]) if self.command else ""


def default_runners() -> dict[str, RunnerConfig]:
    return {
        name: RunnerConfig(enabled=False, command=command, args=args)
        for name, (command, args) in _DEFAULTS.items()
    }


def acp_root(directory: Path | None = None) -> Path:
    if directory is not None:
        path = directory
    else:
        raw = os.environ.get("JONATHAN_ACP_DIR", "").strip()
        path = Path(raw) if raw else Path.home() / ".clawd" / "acp"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def settings_path(directory: Path | None = None, *, user_id: str | None = None) -> Path:
    user = user_id or current_user_id()
    return acp_root(directory) / f"settings-{user}.json"


def load_runners(directory: Path | None = None, *, user_id: str | None = None) -> dict[str, RunnerConfig]:
    runners = default_runners()
    path = settings_path(directory, user_id=user_id)
    if not path.is_file():
        return runners
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return runners
    stored = raw.get("runners") if isinstance(raw, dict) else None
    if not isinstance(stored, dict):
        return runners
    for name, item in stored.items():
        if name not in runners or not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip() or runners[name].command
        args_raw = item.get("args")
        if isinstance(args_raw, list):
            args = tuple(str(part) for part in args_raw)
        else:
            args = runners[name].args
        runners[name] = RunnerConfig(
            enabled=bool(item.get("enabled")),
            command=command,
            args=args,
        )
    return runners


def save_runners(
    runners: dict[str, RunnerConfig],
    directory: Path | None = None,
    *,
    user_id: str | None = None,
) -> None:
    path = settings_path(directory, user_id=user_id)
    payload = {
        "runners": {
            name: {
                "enabled": runners[name].enabled,
                "command": runners[name].command,
                "args": list(runners[name].args),
            }
            for name in RUNNER_IDS
            if name in runners
        }
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        return


def public_runners(directory: Path | None = None, *, user_id: str | None = None) -> dict[str, object]:
    runners = load_runners(directory, user_id=user_id)
    return {
        "runners": [
            {
                "id": name,
                "label": RUNNER_LABELS[name],
                "enabled": runners[name].enabled,
                "command": runners[name].command,
                "args": list(runners[name].args),
            }
            for name in RUNNER_IDS
        ]
    }


def update_runners(
    changes: object,
    directory: Path | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    """Apply a settings-panel update. Unknown runner ids are refused."""
    rows = changes
    if isinstance(changes, dict):
        rows = changes.get("runners", changes)
    if isinstance(rows, dict):
        rows = [{"id": key, **value} if isinstance(value, dict) else {"id": key} for key, value in rows.items()]
    if not isinstance(rows, list):
        raise ValueError("runners must be a list")
    runners = load_runners(directory, user_id=user_id)
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("each runner must be an object")
        name = str(item.get("id") or "").strip()
        if name not in runners:
            raise ValueError(f"unknown ACP runner: {name}")
        current = runners[name]
        default = default_runners()[name]
        enabled = bool(item["enabled"]) if "enabled" in item else current.enabled
        if "command" in item:
            command_text = str(item.get("command") or "").strip()
        else:
            command_text = current.command
        if not command_text or any(char in command_text for char in "\n\r\x00"):
            command_text = default.command
            args = default.args
        elif "args" in item:
            args = _parse_args(item.get("args"))
        else:
            args = current.args
        runners[name] = RunnerConfig(enabled=enabled, command=command_text, args=args)
    save_runners(runners, directory, user_id=user_id)
    return public_runners(directory, user_id=user_id)


def _parse_args(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(part) for part in value if str(part).strip())
    text = str(value or "").strip()
    if not text:
        return ()
    return tuple(shlex.split(text))
