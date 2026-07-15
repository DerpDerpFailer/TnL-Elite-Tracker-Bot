"""Typed shapes for the single-file JSON store and small pure helpers around them.

The JSON file is the source of truth; these TypedDicts exist purely to keep the
rest of the codebase type-checked, not to enforce anything at runtime.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, TypedDict

from bot.constants import DEFAULT_ZONES, SCHEMA_VERSION


class Config(TypedDict):
    channel_id: int | None
    alert_channel_id: int | None
    alert_role_id: int | None
    alert_offset_minutes: int
    timezone: str
    perpetual_message_id: int | None
    admin_role_id: int | None


class ZoneState(TypedDict):
    display_name: str
    cooldown_minutes: int
    last_kill_at: float | None
    last_kill_by: str | None
    window_start: float | None
    window_end: float | None
    pre_alert_sent: bool
    start_alert_sent: bool


HistoryEventType = Literal["kill", "noshow"]


class HistoryEntry(TypedDict):
    type: HistoryEventType
    timestamp: float
    user_id: int
    user_name: str


class UndoEntry(TypedDict):
    zone_state: ZoneState
    history_len: int


class RootData(TypedDict):
    version: int
    config: Config
    zones: dict[str, ZoneState]
    history: dict[str, list[HistoryEntry]]
    undo: dict[str, UndoEntry]


class ZonePhase(str, Enum):
    NO_DATA = "no_data"
    WAITING = "waiting"
    IMMINENT = "imminent"
    ACTIVE = "active"


def build_zone_state(display_name: str, cooldown_minutes: int) -> ZoneState:
    return ZoneState(
        display_name=display_name,
        cooldown_minutes=cooldown_minutes,
        last_kill_at=None,
        last_kill_by=None,
        window_start=None,
        window_end=None,
        pre_alert_sent=False,
        start_alert_sent=False,
    )


def build_seed_data() -> RootData:
    """Fresh JSON structure seeded with the current default zones.

    Called only when /data/elite.json does not exist yet on first boot.
    """
    return RootData(
        version=SCHEMA_VERSION,
        config=Config(
            channel_id=None,
            alert_channel_id=None,
            alert_role_id=None,
            alert_offset_minutes=15,
            timezone="Europe/Paris",
            perpetual_message_id=None,
            admin_role_id=None,
        ),
        zones={
            slug: build_zone_state(meta["display_name"], meta["cooldown_minutes"])
            for slug, meta in DEFAULT_ZONES.items()
        },
        history={slug: [] for slug in DEFAULT_ZONES},
        undo={},
    )


def zone_phase(zone: ZoneState, now: float, imminent_threshold_minutes: int) -> ZonePhase:
    if zone["window_start"] is None or zone["window_end"] is None:
        return ZonePhase.NO_DATA
    if zone["window_start"] <= now <= zone["window_end"]:
        return ZonePhase.ACTIVE
    seconds_until = zone["window_start"] - now
    if 0 < seconds_until <= imminent_threshold_minutes * 60:
        return ZonePhase.IMMINENT
    return ZonePhase.WAITING
