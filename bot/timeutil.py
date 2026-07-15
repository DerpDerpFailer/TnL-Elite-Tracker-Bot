"""Timezone-aware parsing helpers for manual time/duration input."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_DURATION_RE = re.compile(r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m?)?$")


def parse_duration_to_minutes(raw: str) -> int:
    """Parse strings like '4h', '5h30', '5h30m' or '90m' into total minutes.

    Raises ValueError if the string can't be parsed or resolves to <= 0.
    """
    cleaned = raw.strip().lower().replace(" ", "")
    match = _DURATION_RE.match(cleaned) if cleaned else None
    if not match or not (match.group("hours") or match.group("minutes")):
        raise ValueError(raw)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    total = hours * 60 + minutes
    if total <= 0:
        raise ValueError(raw)
    return total


def get_zoneinfo(tz_name: str) -> ZoneInfo:
    """Raises zoneinfo.ZoneInfoNotFoundError if tz_name is not a valid IANA zone."""
    return ZoneInfo(tz_name)


def parse_zone_datetime(raw: str | None, tz: ZoneInfo, now: datetime) -> datetime:
    """Parse a user-supplied kill time into an aware datetime in `tz`.

    Accepts 'HH:MM' (assumed today) or 'DD/MM HH:MM' (assumed current year).
    A parsed time that lands in the future is walked back a day (HH:MM) or a
    year (DD/MM HH:MM) — a kill can't have happened ahead of `now`, and this
    covers the common case of reporting a kill just after local midnight.
    Raises ValueError with the original string if nothing matches.
    """
    if raw is None or not raw.strip():
        return now

    text = raw.strip()

    try:
        parsed = datetime.strptime(text, "%d/%m %H:%M")
    except ValueError:
        pass
    else:
        candidate = parsed.replace(year=now.year, tzinfo=tz)
        if candidate > now + timedelta(minutes=5):
            candidate = candidate.replace(year=now.year - 1)
        return candidate

    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError:
        pass
    else:
        candidate = now.replace(
            hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
        )
        if candidate > now + timedelta(minutes=5):
            candidate -= timedelta(days=1)
        return candidate

    raise ValueError(raw)


def to_epoch(dt: datetime) -> int:
    return int(dt.timestamp())
