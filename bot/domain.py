"""Pure(ish) domain logic mutating RootData in place.

These functions know nothing about Discord — they operate on the plain dicts
that make up the JSON document. Callers (cogs, alert loop) are responsible for
holding `storage.lock` around a mutate-then-`storage.save()` sequence.
"""
from __future__ import annotations

import re
from copy import deepcopy

from bot.constants import MAX_HISTORY_PER_ZONE, SPAWN_WINDOW_MINUTES
from bot.models import HistoryEntry, RootData, ZoneState, build_zone_state


def slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return slug


def _snapshot_for_undo(data: RootData, zone_key: str) -> None:
    data["undo"][zone_key] = {
        "zone_state": deepcopy(data["zones"][zone_key]),
        "history_len": len(data["history"][zone_key]),
    }


def _append_history(data: RootData, zone_key: str, entry: HistoryEntry) -> None:
    history = data["history"][zone_key]
    history.append(entry)
    if len(history) > MAX_HISTORY_PER_ZONE:
        del history[: len(history) - MAX_HISTORY_PER_ZONE]


def record_kill(
    data: RootData, zone_key: str, timestamp: float, user_id: int, user_name: str
) -> ZoneState:
    _snapshot_for_undo(data, zone_key)

    zone = data["zones"][zone_key]
    window_start = timestamp + zone["cooldown_minutes"] * 60
    window_end = window_start + SPAWN_WINDOW_MINUTES * 60

    zone["last_kill_at"] = timestamp
    zone["last_kill_by"] = user_name
    zone["window_start"] = window_start
    zone["window_end"] = window_end
    zone["pre_alert_sent"] = False
    zone["start_alert_sent"] = False

    _append_history(
        data,
        zone_key,
        HistoryEntry(type="kill", timestamp=timestamp, user_id=user_id, user_name=user_name),
    )
    return zone


def record_noshow(
    data: RootData, zone_key: str, now: float, user_id: int, user_name: str
) -> ZoneState | None:
    """Returns None if the zone has no active window to reschedule."""
    zone = data["zones"][zone_key]
    if zone["window_start"] is None:
        return None

    _snapshot_for_undo(data, zone_key)

    missed_window_start = zone["window_start"]
    new_window_start = missed_window_start + zone["cooldown_minutes"] * 60
    new_window_end = new_window_start + SPAWN_WINDOW_MINUTES * 60

    zone["window_start"] = new_window_start
    zone["window_end"] = new_window_end
    zone["pre_alert_sent"] = False
    zone["start_alert_sent"] = False

    _append_history(
        data,
        zone_key,
        HistoryEntry(type="noshow", timestamp=now, user_id=user_id, user_name=user_name),
    )
    return zone


def undo_last(data: RootData, zone_key: str) -> bool:
    entry = data["undo"].get(zone_key)
    if entry is None:
        return False
    data["zones"][zone_key] = entry["zone_state"]
    data["history"][zone_key] = data["history"][zone_key][: entry["history_len"]]
    del data["undo"][zone_key]
    return True


def add_zone(data: RootData, zone_key: str, display_name: str, cooldown_minutes: int) -> None:
    data["zones"][zone_key] = build_zone_state(display_name, cooldown_minutes)
    data["history"][zone_key] = []


def remove_zone(data: RootData, zone_key: str) -> None:
    data["zones"].pop(zone_key, None)
    data["history"].pop(zone_key, None)
    data["undo"].pop(zone_key, None)


def reset_zone(data: RootData, zone_key: str) -> None:
    """Clears last kill/window/history/undo for a zone, keeping its display
    name and cooldown (and its map file, which lives outside the JSON)."""
    zone = data["zones"][zone_key]
    data["zones"][zone_key] = build_zone_state(zone["display_name"], zone["cooldown_minutes"])
    data["history"][zone_key] = []
    data["undo"].pop(zone_key, None)


def kill_intervals_minutes(history: list[HistoryEntry], max_intervals: int = 10) -> list[float]:
    kills = sorted((h for h in history if h["type"] == "kill"), key=lambda h: h["timestamp"])
    diffs = [
        (kills[i]["timestamp"] - kills[i - 1]["timestamp"]) / 60 for i in range(1, len(kills))
    ]
    return diffs[-max_intervals:]
