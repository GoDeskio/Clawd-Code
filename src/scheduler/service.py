"""Persistent local scheduler.

Jobs live in a per-user SQLite file under the home directory. The default
timezone is America/Phoenix. Task mode ``text`` delivers the prompt as a
message. Task mode ``agent`` runs it through the same tool loop, so shell
approvals and the shell guard still apply.

Missed runs inside 60 seconds are coalesced into one catch-up. Older missed
runs are skipped and recorded in the log instead of replayed.

Adapted from Octop's cron manager (MIT). This port does not use APScheduler,
and it does not call a hosted service.

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.agent.memory import current_user_id
from src.secret_mask import mask_secrets

from .expr import Trigger, advance_interval, next_after, parse_trigger, zone_or_default

DEFAULT_TIMEZONE = "America/Phoenix"
MISFIRE_GRACE_SECONDS = 60
PROMPT_MAX = 2000
NAME_MAX = 80
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    trigger_spec TEXT NOT NULL,
    display_schedule TEXT NOT NULL,
    prompt TEXT NOT NULL,
    task_type TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    recurring INTEGER NOT NULL,
    timezone TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    next_run_at TEXT,
    last_run_at TEXT,
    last_status TEXT,
    last_error TEXT,
    PRIMARY KEY (user_id, id)
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_user_job ON logs (user_id, job_id, id);
"""

_SPOKEN_SECRET_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|api[ _-]?key|secret(?:[ _-]?key)?|access[ _-]?token|token)\s+is\s+\S+"
)

_USAGE = (
    "Usage: /cron list | /cron run <id> | /cron enable <id> | /cron disable <id> "
    "| /cron delete <id> | /cron logs [id]\n"
    "Jobs are stored on this machine. The default timezone is America/Phoenix."
)


def scheduler_dir(context: Any | None = None) -> Path:
    override = getattr(context, "scheduler_dir", None) if context is not None else None
    path = Path(override) if override else Path.home() / ".clawd" / "scheduler"
    path.mkdir(parents=True, exist_ok=True)
    return path


def scheduler_db_path(context: Any | None = None) -> Path:
    return scheduler_dir(context) / f"scheduler-{current_user_id()}.sqlite"


def create_job(
    context: Any | None,
    *,
    cron: str,
    prompt: str,
    task_type: str = "text",
    name: str | None = None,
    enabled: bool = True,
    recurring: bool | None = None,
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    mode = _require_task_type(task_type)
    cleaned = _require_prompt(prompt)
    tz = zone_or_default(timezone_name)
    trigger = parse_trigger(cron, tz)
    moment = _moment(now, tz)
    repeats = bool(recurring) if recurring is not None else trigger.kind != "date"
    if trigger.kind == "date":
        repeats = False
    job_id = uuid.uuid4().hex[:12]
    label = _job_name(name, cleaned, job_id)
    created = _iso(moment)
    nxt = _initial_next(trigger, moment, tz)
    user_id = current_user_id()
    with _LOCK:
        conn = _connect(context)
        try:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, user_id, name, trigger_spec, display_schedule, prompt,
                    task_type, enabled, recurring, timezone, created_at, updated_at,
                    next_run_at, last_run_at, last_status, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    job_id,
                    user_id,
                    label,
                    trigger.spec,
                    str(cron).strip(),
                    cleaned,
                    mode,
                    1 if enabled else 0,
                    1 if repeats else 0,
                    getattr(tz, "key", DEFAULT_TIMEZONE),
                    created,
                    created,
                    _iso(nxt) if nxt is not None else None,
                ),
            )
            _write_log(conn, user_id, job_id, moment, "created", f"Created {mode} job {label}")
            conn.commit()
            row = _get_row(conn, user_id, job_id)
        finally:
            conn.close()
    assert row is not None
    return _public_job(row)


def list_jobs(context: Any | None = None, *, include_disabled: bool = True) -> list[dict[str, Any]]:
    user_id = current_user_id()
    with _LOCK:
        conn = _connect(context)
        try:
            if include_disabled:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs WHERE user_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs WHERE user_id = ? AND enabled = 1
                    ORDER BY created_at ASC, id ASC
                    """,
                    (user_id,),
                ).fetchall()
        finally:
            conn.close()
    return [_public_job(row) for row in rows]


def set_enabled(context: Any | None, job_id: str, enabled: bool) -> dict[str, Any]:
    user_id = current_user_id()
    moment = datetime.now(timezone.utc)
    with _LOCK:
        conn = _connect(context)
        try:
            row = _get_row(conn, user_id, job_id)
            if row is None:
                raise KeyError(job_id)
            conn.execute(
                """
                UPDATE jobs SET enabled = ?, updated_at = ? WHERE user_id = ? AND id = ?
                """,
                (1 if enabled else 0, _iso(moment), user_id, job_id),
            )
            _write_log(
                conn,
                user_id,
                job_id,
                moment,
                "enabled" if enabled else "disabled",
                "Job enabled" if enabled else "Job disabled",
            )
            conn.commit()
            updated = _get_row(conn, user_id, job_id)
        finally:
            conn.close()
    assert updated is not None
    return _public_job(updated)


def delete_job(context: Any | None, job_id: str) -> bool:
    user_id = current_user_id()
    moment = datetime.now(timezone.utc)
    with _LOCK:
        conn = _connect(context)
        try:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE user_id = ? AND id = ?",
                (user_id, job_id),
            )
            removed = cursor.rowcount > 0
            if removed:
                _write_log(conn, user_id, job_id, moment, "deleted", "Job deleted")
            conn.commit()
        finally:
            conn.close()
    return removed


def list_logs(
    context: Any | None = None,
    job_id: str | None = None,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    user_id = current_user_id()
    bounded = max(1, min(int(limit), 200))
    with _LOCK:
        conn = _connect(context)
        try:
            if job_id:
                rows = conn.execute(
                    """
                    SELECT id, job_id, at, status, message FROM logs
                    WHERE user_id = ? AND job_id = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (user_id, job_id, bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, job_id, at, status, message FROM logs
                    WHERE user_id = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (user_id, bounded),
                ).fetchall()
        finally:
            conn.close()
    return [
        {
            "id": row["id"],
            "job_id": row["job_id"],
            "at": row["at"],
            "status": row["status"],
            "message": row["message"],
        }
        for row in reversed(rows)
    ]


def run_now(context: Any | None, job_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Run one job immediately. The schedule itself is left in place."""
    user_id = current_user_id()
    with _LOCK:
        conn = _connect(context)
        try:
            row = _get_row(conn, user_id, job_id)
        finally:
            conn.close()
    if row is None:
        raise KeyError(job_id)
    tz = zone_or_default(row["timezone"])
    moment = _moment(now, tz)
    return _perform(context, row, moment, manual=True)


def catch_up(context: Any | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """Run due jobs and record missed runs that fell outside the grace window."""
    user_id = current_user_id()
    with _LOCK:
        conn = _connect(context)
        try:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? AND enabled = 1 ORDER BY next_run_at ASC, id ASC",
                (user_id,),
            ).fetchall()
            snapshots = [dict(row) for row in rows]
        finally:
            conn.close()
    ran: list[str] = []
    missed: list[str] = []
    errors: list[dict[str, str]] = []
    for snap in snapshots:
        tz = zone_or_default(snap["timezone"])
        moment = _moment(now, tz)
        plan = _plan_due(snap, moment, tz)
        if plan is None:
            continue
        if plan["run"]:
            try:
                _perform(context, snap, moment, manual=False, skipped=plan["skipped"])
                ran.append(snap["id"])
            except Exception as exc:
                errors.append({"id": snap["id"], "error": _clip(mask_secrets(str(exc)))})
            if plan["skipped"]:
                missed.append(snap["id"])
        else:
            _skip_missed(context, snap, moment, plan["skipped"])
            missed.append(snap["id"])
    return {"ran": ran, "missed": missed, "errors": errors}


def format_cron_command(args: str, context: Any | None = None) -> str:
    parts = (args or "").strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    rest = parts[1].strip() if len(parts) > 1 else ""
    try:
        if action in {"list", "ls"}:
            return _format_list(context)
        if action in {"logs", "log"}:
            return _format_logs(context, rest or None)
        if action in {"run", "run-now", "now"}:
            if not rest:
                return "Usage: /cron run <id>"
            result = run_now(context, rest.split()[0])
            return f"Ran {result['id']} ({result['task_type']}): {result['output']}"
        if action in {"enable", "disable"}:
            if not rest:
                return f"Usage: /cron {action} <id>"
            job = set_enabled(context, rest.split()[0], action == "enable")
            state = "enabled" if job["enabled"] else "disabled"
            return f"Job {job['id']} {state}."
        if action in {"delete", "rm"}:
            if not rest:
                return "Usage: /cron delete <id>"
            job_id = rest.split()[0]
            if delete_job(context, job_id):
                return f"Deleted job {job_id}."
            return f"No job with id {job_id} for this user."
    except KeyError as exc:
        return f"No job with id {exc.args[0]} for this user."
    except ValueError as exc:
        return str(exc)
    return _USAGE


def _format_list(context: Any | None) -> str:
    rows = list_jobs(context)
    header = f"Local schedules for {current_user_id()} ({scheduler_db_path(context)}):"
    if not rows:
        return header + "\n\nNo scheduled jobs."
    lines = [header, ""]
    for row in rows:
        state = "enabled" if row["enabled"] else "disabled"
        lines.append(
            f"  {row['id']}  [{state}] {row['task_type']}  {row['cron']}  {row['name']}"
        )
    lines.append("")
    lines.append("Run one now with: /cron run <id>")
    return "\n".join(lines)


def _format_logs(context: Any | None, job_id: str | None) -> str:
    rows = list_logs(context, job_id)
    if not rows:
        return "No scheduler logs."
    lines = ["Scheduler logs:", ""]
    for row in rows:
        lines.append(f"  {row['at']}  {row['job_id']}  {row['status']}  {row['message']}")
    return "\n".join(lines)


def _perform(
    context: Any | None,
    row: sqlite3.Row | dict[str, Any],
    moment: datetime,
    *,
    manual: bool,
    skipped: int = 0,
) -> dict[str, Any]:
    job = dict(row)
    tz = zone_or_default(job["timezone"])
    status = "ok"
    error = ""
    try:
        output = _execute(job, context)
    except Exception as exc:
        status = "error"
        error = _clip(mask_secrets(str(exc)))
        output = error
    user_id = job["user_id"]
    finished = _moment(moment, tz)
    with _LOCK:
        conn = _connect(context)
        try:
            current = _get_row(conn, user_id, job["id"])
            if current is None:
                raise KeyError(job["id"])
            recurring = bool(current["recurring"])
            enabled = bool(current["enabled"])
            nxt = current["next_run_at"]
            if not manual:
                if status == "ok" and not recurring:
                    enabled = False
                    nxt = None
                else:
                    trigger = parse_trigger(current["trigger_spec"], tz)
                    anchor = _parse_iso(current["created_at"]) or finished
                    following = _next_future(trigger, finished, tz, anchor)
                    nxt = _iso(following) if following is not None else None
                    if following is None:
                        enabled = False
            message = output if status == "ok" else error
            if skipped and status == "ok":
                message = f"Coalesced {skipped} missed run(s) into this one. {message}"
            conn.execute(
                """
                UPDATE jobs
                SET enabled = ?, next_run_at = ?, last_run_at = ?, last_status = ?,
                    last_error = ?, updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (
                    1 if enabled else 0,
                    nxt,
                    _iso(finished),
                    status,
                    error or None,
                    _iso(finished),
                    user_id,
                    job["id"],
                ),
            )
            if skipped:
                _write_log(
                    conn,
                    user_id,
                    job["id"],
                    finished,
                    "missed",
                    f"Coalesced {skipped} missed run(s) inside the {MISFIRE_GRACE_SECONDS} second grace window.",
                )
            _write_log(conn, user_id, job["id"], finished, status, _clip(message))
            conn.commit()
        finally:
            conn.close()
    if status == "error" and not manual:
        raise RuntimeError(error or "scheduled job failed")
    return {
        "id": job["id"],
        "status": status,
        "task_type": job["task_type"],
        "output": output,
    }


def _skip_missed(context: Any | None, row: dict[str, Any], moment: datetime, skipped: int) -> None:
    tz = zone_or_default(row["timezone"])
    trigger = parse_trigger(row["trigger_spec"], tz)
    anchor = _parse_iso(row["created_at"]) or moment
    following = _next_future(trigger, moment, tz, anchor)
    enabled = bool(row["recurring"]) and following is not None
    message = (
        f"Skipped {skipped} missed run(s). "
        f"The latest was outside the {MISFIRE_GRACE_SECONDS} second grace window."
    )
    with _LOCK:
        conn = _connect(context)
        try:
            current = _get_row(conn, row["user_id"], row["id"])
            if current is None or not current["enabled"]:
                return
            conn.execute(
                """
                UPDATE jobs
                SET enabled = ?, next_run_at = ?, last_status = ?, last_error = ?, updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (
                    1 if enabled else 0,
                    _iso(following) if following is not None else None,
                    "missed",
                    message,
                    _iso(moment),
                    row["user_id"],
                    row["id"],
                ),
            )
            _write_log(conn, row["user_id"], row["id"], moment, "missed", message)
            conn.commit()
        finally:
            conn.close()


def _plan_due(row: dict[str, Any], now: datetime, tz: ZoneInfo) -> dict[str, Any] | None:
    nxt = _parse_iso(row.get("next_run_at") or "")
    if nxt is None or nxt > now:
        return None
    trigger = parse_trigger(row["trigger_spec"], tz)
    times: list[datetime] = []
    cursor: datetime | None = nxt.astimezone(tz)
    guard = 0
    while cursor is not None and cursor <= now and guard < 10000:
        times.append(cursor)
        guard += 1
        cursor = _step(trigger, cursor, tz)
    if not times:
        return None
    latest = times[-1]
    lateness = (now - latest).total_seconds()
    if lateness <= MISFIRE_GRACE_SECONDS:
        return {"run": True, "skipped": max(0, len(times) - 1)}
    return {"run": False, "skipped": len(times)}


def _step(trigger: Trigger, cursor: datetime, tz: ZoneInfo) -> datetime | None:
    if trigger.kind == "date":
        return None
    if trigger.kind == "interval":
        assert trigger.interval_seconds is not None
        return cursor + timedelta(seconds=trigger.interval_seconds)
    return next_after(trigger, cursor, tz)


def _initial_next(trigger: Trigger, now: datetime, tz: ZoneInfo) -> datetime | None:
    if trigger.kind == "date":
        return trigger.run_at
    if trigger.kind == "interval":
        assert trigger.interval_seconds is not None
        return advance_interval(now, now, trigger.interval_seconds, tz)
    return next_after(trigger, now, tz)


def _next_future(
    trigger: Trigger,
    now: datetime,
    tz: ZoneInfo,
    anchor: datetime,
) -> datetime | None:
    if trigger.kind == "date":
        return None
    if trigger.kind == "interval":
        assert trigger.interval_seconds is not None
        return advance_interval(anchor, now, trigger.interval_seconds, tz)
    return next_after(trigger, now, tz)


def _execute(job: dict[str, Any], context: Any | None) -> str:
    prompt = str(job["prompt"])
    if job["task_type"] == "text":
        return prompt
    provider = getattr(context, "provider", None)
    registry = getattr(context, "tool_registry", None)
    if provider is None or registry is None:
        raise RuntimeError("agent tasks need a provider and tool registry on the tool context")
    from src.agent.conversation import Conversation
    from src.tool_system.agent_loop import run_agent_loop

    conversation = Conversation()
    conversation.add_user_message(prompt)
    result = run_agent_loop(
        conversation=conversation,
        provider=provider,
        tool_registry=registry,
        tool_context=context,
        max_turns=8,
        stream=False,
    )
    text = (result.response_text or "").strip()
    if not text:
        raise RuntimeError("agent run produced no visible response")
    return _clip(mask_secrets(text))


def _connect(context: Any | None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(scheduler_db_path(context)), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _get_row(conn: sqlite3.Connection, user_id: str, job_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM jobs WHERE user_id = ? AND id = ?",
        (user_id, job_id),
    ).fetchone()


def _write_log(
    conn: sqlite3.Connection,
    user_id: str,
    job_id: str,
    moment: datetime,
    status: str,
    message: str,
) -> None:
    conn.execute(
        "INSERT INTO logs (user_id, job_id, at, status, message) VALUES (?, ?, ?, ?, ?)",
        (user_id, job_id, _iso(moment), status, _clip(mask_secrets(message))),
    )


def _public_job(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    return {
        "id": item["id"],
        "name": item["name"],
        "cron": item["display_schedule"],
        "humanSchedule": item["display_schedule"],
        "prompt": item["prompt"],
        "task_type": item["task_type"],
        "enabled": bool(item["enabled"]),
        "recurring": bool(item["recurring"]),
        "durable": True,
        "timezone": item["timezone"],
        "next_run_at": item["next_run_at"],
        "last_run_at": item["last_run_at"],
        "last_status": item["last_status"],
        "created_at": item["created_at"],
    }


def _require_task_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in {"text", "agent"}:
        raise ValueError("task_type must be 'text' or 'agent'")
    return text


def _require_prompt(prompt: str) -> str:
    raw = _SPOKEN_SECRET_RE.sub("[redacted]", str(prompt or ""))
    cleaned = _clip(mask_secrets(raw), PROMPT_MAX)
    if not cleaned.strip():
        raise ValueError("prompt must not be empty")
    return cleaned.strip()


def _job_name(name: str | None, prompt: str, job_id: str) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        text = " ".join(prompt.split())[:40] or job_id
    text = _clip(mask_secrets(text), NAME_MAX)
    if len(text) > NAME_MAX:
        raise ValueError(f"name must be at most {NAME_MAX} characters")
    return text or job_id


def _moment(now: datetime | None, tz: ZoneInfo) -> datetime:
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _iso(moment: datetime | None) -> str:
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clip(text: str, limit: int = PROMPT_MAX) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned
