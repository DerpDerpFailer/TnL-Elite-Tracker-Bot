"""Best-effort fallback: when a zone's spawn timer is missing or stale, ask
the (unofficial, community-run) mmopartybuilder.eu boss-timer map whether the
Elite has already been killed, and adopt that kill time if it's newer than
what we have.

This talks to an internal API of that site (discovered by inspecting its
network traffic, not a published/documented integration) — it could change
shape or disappear at any time, so every failure mode here degrades to
"do nothing" rather than raising. `fetch_zone_kill_time` in particular must
never raise: a broken third-party site must never affect this bot's own
timers or block anything.

The site publishes one map per PvP world/server (see SERVERS), each with the
same 7 region pages in the same order (Laslan, Laslan Abyss, Stonegard,
Stonegard Abyss, Talandre, Talandre Abyss, Nix) — confirmed by the "Abyss"
pages sharing `masterPoiId`s with their master map (Sacred), i.e. they're
synced clones with independently-tracked timers. Each region page's
`region_timer`-icon POI is the zone-wide Elite timer we care about;
`cooldownResetAt` on that POI is the last confirmed kill time.
"""
from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import aiohttp

from bot import domain
from bot.models import ZoneState

if TYPE_CHECKING:
    from bot.main import EliteBot

logger = logging.getLogger(__name__)

BASE_URL = "https://mmopartybuilder.eu"

# A kill applied from this source isn't reported by a real Discord user, but
# last_kill_by/history are only ever rendered as plain text, never a mention
# (see bot/strings.py:status_row), so a descriptive string is safe here.
FALLBACK_REPORTER_ID = 0
FALLBACK_REPORTER_NAME = "mmopartybuilder.eu (auto)"

# server_key -> (mapId, first imageId of its 7-page region block)
SERVERS: dict[str, tuple[int, int]] = {
    "sacred": (4, 23),
    "fearless": (6, 31),
    "usurper": (7, 38),
    "indomitable": (8, 45),
    "sophia": (9, 52),
}

SERVER_DISPLAY_NAMES: dict[str, str] = {
    "sacred": "Sacred",
    "fearless": "Fearless",
    "usurper": "Usurper",
    "indomitable": "Indomitable",
    "sophia": "Sophia",
}

# our zone_key -> offset within a server's 7-image region block. Every zone
# we currently track has a match; a future custom zone (/elite-config
# zone-add) simply won't be eligible for fallback sync.
_ZONE_OFFSETS: dict[str, int] = {
    "laslan": 0,
    "laslan-dungeon": 1,
    "stonegard": 2,
    "stonegard-dungeon": 3,
    "talandre": 4,
    "talandre-dungeon": 5,
    "nix": 6,
}


class FallbackSyncResult(str, Enum):
    APPLIED = "applied"
    NO_NEWER_DATA = "no_newer_data"
    FETCH_FAILED = "fetch_failed"
    UNKNOWN_ZONE = "unknown_zone"
    NOT_ELIGIBLE = "not_eligible"


def _resolve_target(server_key: str, zone_key: str) -> tuple[int, int] | None:
    server = SERVERS.get(server_key)
    offset = _ZONE_OFFSETS.get(zone_key)
    if server is None or offset is None:
        return None
    map_id, first_image_id = server
    return map_id, first_image_id + offset


def _parse_region_timer_cooldown_reset(payload: object) -> float | None:
    """Pure parsing step, kept separate from the network call so it's
    testable with plain dicts. Returns None for any shape that doesn't match
    what's expected — this is an undocumented third-party endpoint that could
    change at any time."""
    if not isinstance(payload, dict):
        return None
    pois = payload.get("pois")
    if not isinstance(pois, list):
        return None

    for poi in pois:
        if not isinstance(poi, dict) or poi.get("icon") != "region_timer":
            continue
        reset_at = poi.get("cooldownResetAt")
        if not isinstance(reset_at, str) or not reset_at:
            return None
        try:
            return datetime.fromisoformat(reset_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    return None


async def fetch_zone_kill_time(
    server_key: str, zone_key: str, *, timeout: float = 5.0
) -> float | None:
    """Returns the last confirmed kill time (epoch seconds) mmopartybuilder.eu
    has for this zone/server, or None on absolutely any failure — bad
    mapping, network error, timeout, non-200, unexpected JSON shape. Never
    raises."""
    target = _resolve_target(server_key, zone_key)
    if target is None:
        return None
    map_id, image_id = target
    url = f"{BASE_URL}/api/maps/{map_id}/images/{image_id}/pois"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001 - a third-party endpoint must never crash us
        logger.warning("Fallback fetch failed for %s/%s: %s", server_key, zone_key, exc)
        return None

    return _parse_region_timer_cooldown_reset(payload)


async def sync_zone_from_fallback(
    bot: "EliteBot", zone_key: str
) -> tuple[FallbackSyncResult, ZoneState | None]:
    """Fetches the zone's timer from the configured fallback server and, only
    if it's strictly newer than what we already have, records it as a kill
    (same effect as /elite-killed, minus a real Discord reporter). Safe to
    call whether or not the fallback feature is "enabled" — that flag only
    gates the automatic background check in alerts.py; this function itself
    has no opinion on when it should run."""
    storage = bot.storage
    async with storage.zone_lock(zone_key):
        zone = storage.data["zones"].get(zone_key)
        if zone is None:
            return FallbackSyncResult.UNKNOWN_ZONE, None

        server_key = storage.data["config"]["fallback_server"]
        if _resolve_target(server_key, zone_key) is None:
            return FallbackSyncResult.NOT_ELIGIBLE, None

        kill_ts = await fetch_zone_kill_time(server_key, zone_key)
        if kill_ts is None:
            return FallbackSyncResult.FETCH_FAILED, None

        if zone["last_kill_at"] is not None and kill_ts <= zone["last_kill_at"]:
            return FallbackSyncResult.NO_NEWER_DATA, None

        zone_state = domain.record_kill(
            storage.data, zone_key, kill_ts, FALLBACK_REPORTER_ID, FALLBACK_REPORTER_NAME
        )
        await storage.save()
        return FallbackSyncResult.APPLIED, zone_state
