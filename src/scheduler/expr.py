"""Wall-clock schedules without a third-party scheduler library.

Understands Unix 5-field cron, ``interval:<seconds>``, and ``date:<ISO-8601>``.
Weekdays follow Unix crontab: 0 and 7 are Sunday. A naive date is read in the
job timezone. Python 3.10 compatible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_NAMES_DOW = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}
_NAMES_MON = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_PART_RE = re.compile(
    r"^(?P<first>\*|[A-Za-z0-9]+)(?:-(?P<last>[A-Za-z0-9]+))?(?:/(?P<step>\d+))?$"
)
_MAX_MINUTES = 366 * 24 * 60


@dataclass(frozen=True)
class Trigger:
    """A parsed schedule. ``spec`` is the stored form."""

    kind: str
    spec: str
    minute: frozenset[int] | None = None
    hour: frozenset[int] | None = None
    day: frozenset[int] | None = None
    month: frozenset[int] | None = None
    weekday: frozenset[int] | None = None
    day_restricted: bool = False
    weekday_restricted: bool = False
    interval_seconds: int | None = None
    run_at: datetime | None = None


def default_zone() -> ZoneInfo:
    return ZoneInfo("America/Phoenix")


def zone_or_default(name: str | None) -> ZoneInfo:
    text = (name or "").strip() or "America/Phoenix"
    try:
        return ZoneInfo(text)
    except Exception as exc:
        raise ValueError(f"unknown timezone: {text}") from exc


def parse_trigger(raw: str, tz: ZoneInfo) -> Trigger:
    """Parse a cron expression or an ``interval:`` / ``date:`` / ``cron:`` spec."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("schedule must not be empty")
    kind, _, value = text.partition(":")
    if kind in {"cron", "interval", "date"} and value.strip():
        body = value.strip()
        if kind == "cron":
            return _parse_cron(body, tz)
        if kind == "interval":
            return _parse_interval(body)
        return _parse_date(body, tz)
    if ":" in text and kind not in _NAMES_MON and not _looks_like_cron(text):
        raise ValueError(f"unknown schedule kind: {kind!r}")
    return _parse_cron(text, tz)


def next_after(trigger: Trigger, after: datetime, tz: ZoneInfo) -> datetime | None:
    """Return the next fire time strictly after ``after``, in ``tz``."""
    moment = _aware(after, tz)
    if trigger.kind == "date":
        assert trigger.run_at is not None
        run_at = trigger.run_at.astimezone(tz)
        if run_at > moment:
            return run_at
        return None
    if trigger.kind == "interval":
        assert trigger.interval_seconds is not None
        step = timedelta(seconds=trigger.interval_seconds)
        cursor = moment + step
        return cursor
    return _next_cron(trigger, moment, tz)


def advance_interval(anchor: datetime, after: datetime, seconds: int, tz: ZoneInfo) -> datetime:
    """Next interval boundary strictly after ``after``, aligned to ``anchor``."""
    start = _aware(anchor, tz)
    moment = _aware(after, tz)
    elapsed = (moment - start).total_seconds()
    if elapsed < 0:
        return start
    steps = int(elapsed // seconds) + 1
    return start + timedelta(seconds=steps * seconds)


def _parse_interval(body: str) -> Trigger:
    try:
        seconds = int(body)
    except ValueError as exc:
        raise ValueError("interval seconds must be an integer") from exc
    if seconds <= 0:
        raise ValueError("interval seconds must be a positive integer")
    if seconds > 366 * 24 * 3600:
        raise ValueError("interval is too long")
    return Trigger(kind="interval", spec=f"interval:{seconds}", interval_seconds=seconds)


def _parse_date(body: str, tz: ZoneInfo) -> Trigger:
    try:
        parsed = datetime.fromisoformat(body)
    except ValueError as exc:
        raise ValueError(f"date must be ISO-8601: {body}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    else:
        parsed = parsed.astimezone(tz)
    stored = parsed.astimezone(timezone.utc).isoformat()
    return Trigger(kind="date", spec=f"date:{stored}", run_at=parsed)


def _looks_like_cron(text: str) -> bool:
    return len(text.split()) == 5


def _parse_cron(expression: str, tz: ZoneInfo) -> Trigger:
    del tz
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"cron expression needs 5 fields, got {len(fields)}")
    minute = _parse_field(fields[0], 0, 59)
    hour = _parse_field(fields[1], 0, 23)
    day = _parse_field(fields[2], 1, 31)
    month = _parse_field(fields[3], 1, 12, names=_NAMES_MON)
    weekday = _parse_weekday(fields[4])
    day_restricted = day != frozenset(range(1, 32))
    weekday_restricted = weekday != frozenset(range(0, 7))
    normalized = " ".join(fields)
    return Trigger(
        kind="cron",
        spec=f"cron:{normalized}",
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        weekday=weekday,
        day_restricted=day_restricted,
        weekday_restricted=weekday_restricted,
    )


def _parse_weekday(expr: str) -> frozenset[int]:
    """Unix weekdays. 0 and 7 are both Sunday; names are accepted."""
    values = _parse_field(expr, 0, 7, names=_NAMES_DOW)
    return frozenset(0 if value == 7 else value for value in values)


def _parse_field(
    expr: str,
    low: int,
    high: int,
    *,
    names: dict[str, int] | None = None,
) -> frozenset[int]:
    pieces = [part.strip() for part in expr.split(",") if part.strip()]
    if not pieces:
        raise ValueError(f"empty schedule field: {expr!r}")
    found: set[int] = set()
    for piece in pieces:
        match = _PART_RE.fullmatch(piece)
        if match is None:
            raise ValueError(f"invalid schedule field: {piece!r}")
        first_text = match.group("first")
        last_text = match.group("last")
        step_text = match.group("step")
        step = int(step_text) if step_text is not None else 1
        if step <= 0:
            raise ValueError("schedule step must be greater than 0")
        if first_text == "*":
            if last_text is not None:
                raise ValueError(f"invalid schedule field: {piece!r}")
            start, end = low, high
        else:
            start = _coerce(first_text, low, high, names)
            end = _coerce(last_text, low, high, names) if last_text is not None else start
        if start > end:
            raise ValueError(f"schedule range start is after its end: {piece!r}")
        for value in range(start, end + 1, step):
            if value < low or value > high:
                raise ValueError(f"schedule value {value} is outside {low}-{high}")
            found.add(value)
    if not found:
        raise ValueError(f"schedule field matches nothing: {expr!r}")
    return frozenset(found)


def _coerce(token: str, low: int, high: int, names: dict[str, int] | None) -> int:
    key = token.lower()
    if names and key in names:
        return names[key]
    if not token.isdigit():
        raise ValueError(f"invalid schedule token: {token!r}")
    value = int(token)
    if value < low or value > high:
        raise ValueError(f"schedule value {value} is outside {low}-{high}")
    return value


def _next_cron(trigger: Trigger, after: datetime, tz: ZoneInfo) -> datetime:
    cursor = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_MAX_MINUTES):
        if _cron_match(trigger, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    raise ValueError("no matching cron time within a year")


def _cron_match(trigger: Trigger, moment: datetime) -> bool:
    assert trigger.minute is not None
    assert trigger.hour is not None
    assert trigger.day is not None
    assert trigger.month is not None
    assert trigger.weekday is not None
    if moment.minute not in trigger.minute:
        return False
    if moment.hour not in trigger.hour:
        return False
    if moment.month not in trigger.month:
        return False
    day_ok = moment.day in trigger.day
    unix_dow = (moment.weekday() + 1) % 7
    dow_ok = unix_dow in trigger.weekday
    if trigger.day_restricted and trigger.weekday_restricted:
        return day_ok or dow_ok
    if trigger.day_restricted:
        return day_ok
    if trigger.weekday_restricted:
        return dow_ok
    return True


def _aware(moment: datetime, tz: ZoneInfo) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=tz)
    return moment.astimezone(tz)
