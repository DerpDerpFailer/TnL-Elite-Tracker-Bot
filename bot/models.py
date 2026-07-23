"""Typed shapes for the single-file JSON store and small pure helpers around them.

The JSON file is the source of truth; these TypedDicts exist purely to keep the
rest of the codebase type-checked, not to enforce anything at runtime.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, TypedDict

from bot.constants import DEFAULT_SUBZONES, DEFAULT_ZONES, SCHEMA_VERSION
from bot.slugs import slugify


class Config(TypedDict):
    """Settings shared by every installed guild, since they describe the one
    mutualized boss-timer state (not any particular server's presentation of
    it) — see GuildConfig below for the per-guild settings."""

    alert_offset_minutes: int
    timezone: str
    fallback_enabled: bool
    fallback_server: str
    fallback_threshold_minutes: int
    fallback_found_watch_enabled: bool
    fallback_found_watch_attempts: int
    fallback_found_watch_slow_interval_minutes: int


class GuildConfig(TypedDict):
    """Per-installed-guild settings: which channels/roles *this* server wants
    used, and its own copy of the perpetual status message. Keyed by
    str(guild_id) in RootData.guilds — created empty on install (see
    bot/main.py's on_guild_join) and filled in via /elite-config."""

    channel_id: int | None
    alert_channel_id: int | None
    alert_role_id: int | None
    admin_role_id: int | None
    perpetual_message_id: int | None


class SubzoneState(TypedDict):
    display_name: str
    scouts: list[int]


class ScoutingMessageRef(TypedDict):
    guild_id: int
    channel_id: int
    message_id: int
    subzone_keys: list[str]


class MessageRef(TypedDict):
    guild_id: int
    channel_id: int
    message_id: int


class ZoneState(TypedDict):
    display_name: str
    cooldown_minutes: int
    last_kill_at: float | None
    last_kill_by: str | None
    last_kill_subzone: str | None
    spawn_at: float | None
    pre_alert_sent: bool
    spawn_due_marked: bool
    found_this_cycle: bool
    subzones: dict[str, SubzoneState]
    scouting_messages: list[ScoutingMessageRef]
    found_announcement_messages: list[MessageRef]


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
    guilds: dict[str, GuildConfig]
    zones: dict[str, ZoneState]
    history: dict[str, list[HistoryEntry]]
    undo: dict[str, UndoEntry]


class ZonePhase(str, Enum):
    NO_DATA = "no_data"
    WAITING = "waiting"
    IMMINENT = "imminent"
    ACTIVE = "active"


def build_subzone_state(display_name: str) -> SubzoneState:
    return SubzoneState(display_name=display_name, scouts=[])


def build_guild_config() -> GuildConfig:
    return GuildConfig(
        channel_id=None,
        alert_channel_id=None,
        alert_role_id=None,
        admin_role_id=None,
        perpetual_message_id=None,
    )


def build_zone_state(
    display_name: str,
    cooldown_minutes: int,
    subzone_names: list[str] | None = None,
) -> ZoneState:
    return ZoneState(
        display_name=display_name,
        cooldown_minutes=cooldown_minutes,
        last_kill_at=None,
        last_kill_by=None,
        last_kill_subzone=None,
        spawn_at=None,
        pre_alert_sent=False,
        spawn_due_marked=False,
        found_this_cycle=False,
        subzones={
            slugify(name): build_subzone_state(name) for name in (subzone_names or [])
        },
        scouting_messages=[],
        found_announcement_messages=[],
    )


def build_seed_data() -> RootData:
    """Fresh JSON structure seeded with the current default zones.

    Called only when /data/elite.json does not exist yet on first boot.
    """
    return RootData(
        version=SCHEMA_VERSION,
        config=Config(
            alert_offset_minutes=15,
            timezone="Europe/Paris",
            fallback_enabled=False,
            fallback_server="sacred",
            fallback_threshold_minutes=5,
            fallback_found_watch_enabled=False,
            fallback_found_watch_attempts=10,
            fallback_found_watch_slow_interval_minutes=15,
        ),
        guilds={},
        zones={
            slug: build_zone_state(
                meta["display_name"], meta["cooldown_minutes"], DEFAULT_SUBZONES.get(slug)
            )
            for slug, meta in DEFAULT_ZONES.items()
        },
        history={slug: [] for slug in DEFAULT_ZONES},
        undo={},
    )


def zone_phase(zone: ZoneState, now: float, imminent_threshold_minutes: int) -> ZonePhase:
    if zone["spawn_at"] is None:
        return ZonePhase.NO_DATA
    seconds_until = zone["spawn_at"] - now
    if seconds_until <= 0:
        return ZonePhase.ACTIVE
    if seconds_until <= imminent_threshold_minutes * 60:
        return ZonePhase.IMMINENT
    return ZonePhase.WAITING
