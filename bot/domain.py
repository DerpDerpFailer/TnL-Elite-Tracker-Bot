"""Pure(ish) domain logic mutating RootData in place.

These functions know nothing about Discord — they operate on the plain dicts
that make up the JSON document. Callers (cogs, alert loop) are responsible for
holding the relevant lock (`storage.lock` for structural/config changes,
`storage.zone_lock(key)` for anything scoped to one zone) around a
mutate-then-`storage.save()` sequence.
"""
from __future__ import annotations

from copy import deepcopy

from bot.constants import DEFAULT_SUBZONES, DEFAULT_ZONES, MAX_HISTORY_PER_ZONE
from bot.models import (
    HistoryEntry,
    RootData,
    ZoneState,
    build_subzone_state,
    build_zone_state,
)
from bot.slugs import slugify

__all__ = [
    "slugify",
    "record_kill",
    "record_noshow",
    "undo_last",
    "add_zone",
    "remove_zone",
    "reset_zone",
    "add_subzone",
    "remove_subzone",
    "toggle_scout",
    "mark_found",
    "kill_intervals_minutes",
    "sync_default_zones",
]


def _reset_scouting_state(zone: ZoneState) -> None:
    for subzone in zone["subzones"].values():
        subzone["scouts"] = []
    zone["scouting_messages"] = []
    zone["found_this_cycle"] = False
    zone["found_announcement_messages"] = []


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
    data: RootData,
    zone_key: str,
    timestamp: float,
    user_id: int,
    user_name: str,
    subzone_display_name: str | None = None,
) -> ZoneState:
    _snapshot_for_undo(data, zone_key)

    zone = data["zones"][zone_key]
    spawn_at = timestamp + zone["cooldown_minutes"] * 60

    zone["last_kill_at"] = timestamp
    zone["last_kill_by"] = user_name
    zone["last_kill_subzone"] = subzone_display_name
    zone["spawn_at"] = spawn_at
    zone["pre_alert_sent"] = False
    zone["spawn_due_marked"] = False
    _reset_scouting_state(zone)

    _append_history(
        data,
        zone_key,
        HistoryEntry(type="kill", timestamp=timestamp, user_id=user_id, user_name=user_name),
    )
    return zone


def record_noshow(
    data: RootData, zone_key: str, now: float, user_id: int, user_name: str
) -> ZoneState | None:
    """Returns None if the zone has no pending spawn time to reschedule."""
    zone = data["zones"][zone_key]
    if zone["spawn_at"] is None:
        return None

    _snapshot_for_undo(data, zone_key)

    missed_spawn_at = zone["spawn_at"]
    zone["spawn_at"] = missed_spawn_at + zone["cooldown_minutes"] * 60
    zone["pre_alert_sent"] = False
    zone["spawn_due_marked"] = False
    _reset_scouting_state(zone)

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


def add_zone(
    data: RootData,
    zone_key: str,
    display_name: str,
    cooldown_minutes: int,
    subzone_names: list[str] | None = None,
) -> None:
    data["zones"][zone_key] = build_zone_state(display_name, cooldown_minutes, subzone_names)
    data["history"][zone_key] = []


def sync_default_zones(data: RootData) -> list[str]:
    """Adds any built-in default zone (bot/constants.py DEFAULT_ZONES) that's
    missing from `data`, with its default sub-zones. Existing zones are left
    untouched even if their cooldown/sub-zones have since diverged from the
    defaults. Returns the display names of the zones that were added."""
    added: list[str] = []
    for zone_key, meta in DEFAULT_ZONES.items():
        if zone_key in data["zones"]:
            continue
        add_zone(
            data,
            zone_key,
            meta["display_name"],
            meta["cooldown_minutes"],
            DEFAULT_SUBZONES.get(zone_key),
        )
        added.append(meta["display_name"])
    return added


def remove_zone(data: RootData, zone_key: str) -> None:
    data["zones"].pop(zone_key, None)
    data["history"].pop(zone_key, None)
    data["undo"].pop(zone_key, None)


def reset_zone(data: RootData, zone_key: str) -> None:
    """Clears last kill/window/history/undo for a zone, keeping its display
    name, cooldown and configured sub-zones (and its map files, which live
    outside the JSON) — only each sub-zone's current scout list is cleared."""
    zone = data["zones"][zone_key]
    new_zone = build_zone_state(zone["display_name"], zone["cooldown_minutes"])
    new_zone["subzones"] = zone["subzones"]
    _reset_scouting_state(new_zone)
    data["zones"][zone_key] = new_zone
    data["history"][zone_key] = []
    data["undo"].pop(zone_key, None)


def add_subzone(data: RootData, zone_key: str, subzone_key: str, display_name: str) -> None:
    data["zones"][zone_key]["subzones"][subzone_key] = build_subzone_state(display_name)


def remove_subzone(data: RootData, zone_key: str, subzone_key: str) -> None:
    data["zones"][zone_key]["subzones"].pop(subzone_key, None)


def mark_found(data: RootData, zone_key: str) -> None:
    data["zones"][zone_key]["found_this_cycle"] = True


def toggle_scout(data: RootData, zone_key: str, subzone_key: str, user_id: int) -> bool:
    """Adds or removes user_id from the sub-zone's scout list. Returns True if
    the user is now scouting it, False if they were removed."""
    scouts = data["zones"][zone_key]["subzones"][subzone_key]["scouts"]
    if user_id in scouts:
        scouts.remove(user_id)
        return False
    scouts.append(user_id)
    return True


def kill_intervals_minutes(history: list[HistoryEntry], max_intervals: int = 10) -> list[float]:
    kills = sorted((h for h in history if h["type"] == "kill"), key=lambda h: h["timestamp"])
    diffs = [
        (kills[i]["timestamp"] - kills[i - 1]["timestamp"]) / 60 for i in range(1, len(kills))
    ]
    return diffs[-max_intervals:]
