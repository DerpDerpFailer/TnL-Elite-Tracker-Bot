"""Best-effort fallback: when a zone's spawn timer is missing or stale, ask
the (unofficial, community-run) mmopartybuilder.eu boss-timer map whether the
Elite has already been killed, and adopt that kill time if it's newer than
what we have — closing out the zone's scouting cycle exactly like a real
kill report would (deletes tracked scouting/found messages, posts a "Boss
killed" summary), via bot/scouting.py's shared helper.

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

from bot.models import ZoneState
from bot.scouting import (
    NO_SUBZONE_KEY,
    mark_found_and_announce_locked,
    record_kill_and_close_scouting_locked,
)

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

# our zone_key -> {mmopartybuilder "boss"-icon spot name -> our sub-zone key}.
# Built from the live scouting board for each region (verified by hand,
# 2026-07-20/21) — several mmopartybuilder spots are more granular than our
# own sub-zones (e.g. two "Syleus Abyss - B6" variants), so this is a
# many-to-one mapping in places. A spot with no entry here just can't be
# auto-detected by the found-watch (see bot/alerts.py), which is harmless —
# it only ever adds information, never required.
_SUBZONE_NAME_MAP: dict[str, dict[str, str]] = {
    "laslan": {
        "Urstella Fields": "urstella-fields",
        "Carmine Forest": "carmine-forest",
        "Nesting Grounds": "nesting-grounds",
        "Fonos Basin": "fonos-basin",
        "Ruins of Turayne": "ruins-of-turayne",
        "Purelight Hill": "purelight-hill",
        "Shattered Temple": "shattered-temple",
    },
    "laslan-dungeon": {
        "Shadowed Crypt - 1F": "shadowed-crypt-1f",
        "Shadowed Crypt - 2F": "shadowed-crypt-2f",
        "Shadowed Crypt - B1 (Not confirmed)": "shadowed-crypt-b1",
        "Syleus Abyss - B1": "syleus-b1",
        "Syleus Abyss - B2 (Corridor of Oblivion)": "syleus-b2",
        "Syleus Abyss - B2 (Corridor of Loss)": "syleus-b2",
        "Syleus Abyss - B3": "syleus-b3",
        "Syleus Abyss - B4 (North-East)": "syleus-b4",
        "Syleus Abyss - B4 (South-West)": "syleus-b4",
        "Syleus Abyss - B5": "syleus-b5",
        "Syleus Abyss - B6 (North)": "syleus-b6",
        "Syleus Abyss - B6 (West)": "syleus-b6",
    },
    "stonegard": {
        "Monolith Wastelands": "monolith-wastelands",
        "Abandoned Stonemason Town": "abandoned-stonemason",
        "Daybreak Shore": "daybreak-shore",
        "Manawastes": "manawastes",
        "The Raging Wilds": "raging-wilds",
        "Greyclaw Forest": "greyclaw-forest",
        "Akidu Valley": "akidu-valley",
        "Sandworm Lair (Eastern Hatchery)": "sandworm-lair",
    },
    "stonegard-dungeon": {
        "Ant Nest - 1 (North)": "ant-nest",
        "Ant Nest - 2 (Garbage Dump)": "ant-nest",
        "Ant Nest - 3 (South)": "ant-nest",
        "Sanctum of Desire - 1F": "sanctum-1f",
        "Sanctum of Desire - B1 (Altar of Darkness)": "sanctum-b1",
        "Sanctum of Desire - B1 (Junobote's Study)": "sanctum-b1",
        "Saurodoma - Cave (East)": "saurodoma-in",
        "Saurodoma - Cave (West)": "saurodoma-in",
        "Saurodoma - Outside": "saurodoma-out",
        "Temple of Sylaveth - B1": "sylaveth-b1",
        "Temple of Sylaveth - B2": "sylaveth-b2",
    },
    "talandre": {
        "Swamp of Silence": "swamp-of-silence",
        "Forest of the Great Tree": "the-great-tree",
        "Black Anvil": "black-anvil",
        "Crimson Mansion": "crimson-mansion",
        "Quietis's Demise": "quietiss-demesne",
        "Bercant Manor": "bercant-manor",
    },
    "talandre-dungeon": {
        "Crimson Estate - B2 (3 Central Storage)": "crimson-b2",
        "Crimson Estate - B2 (2 Central Prison)": "crimson-b2",
        "Crimson Estate - B2 (1 Treatment Room)": "crimson-b2",
        "Crimson Estate - B3 (Central Control Room)": "crimson-b3",
        "Crimson Estate - B3 (Storage 1) (Not confirmed)": "crimson-b3",
        "Crimson Estate - B3 (Storage 2) (Not confirmed)": "crimson-b3",
        "Crimson Estate - B3 (Storage 3)": "crimson-b3",
        "Crimson Estate - B3 (Storage 4) (Not confirmed)": "crimson-b3",
        "Crimson Estate - B1": "crimson-b1",
        "Temple of Truth - B1 (Not Confirmed)": "temple-of-truth-b1",
        "Temple of Truth - B2 (Not confirmed)": "temple-of-truth-b2",
        "Temple of Truth - 1F (Unknown)": "temple-of-truth-1f",
        "Bercant Estate - 1F (Lord's Reception Chamber)": "bercant-1f",
        "Bercant Estate - 1F (Banquet Hall)": "bercant-1f",
        "Bercant Estate - 2F (Not confirmed)": "bercant-2f",
        "Bercant Estate - B1": "bercant-b1",
    },
    "nix": {
        "Tumgir Hollow": "tumgir-hollow",
        "Stillreach": "stillreach",
        "Frozen Nightlands": "frozen-nightlands",
        "Entropic Tundra (cave)": "entropic-tundra",
        "Scars of Sacrifice": "scar-of-sacrifice",
    },
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
    and closes out the zone's scouting cycle (deletes tracked scouting/found
    messages, posts a "Boss killed" summary) exactly like a real kill report
    — same effect as /elite-killed, minus a real Discord reporter, and using
    the actual external kill time rather than "now". Safe to call whether or
    not the fallback feature is "enabled" — that flag only gates the
    automatic background check in alerts.py; this function itself has no
    opinion on when it should run."""
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

        # mmopartybuilder.eu only tracks a zone-wide timer, not which
        # specific sub-zone the Elite was found in — NO_SUBZONE_KEY makes
        # the summary embed's sub-zone field say "Unknown", same as a
        # zero-sub-zone zone's generic kill button.
        zone_state = await record_kill_and_close_scouting_locked(
            bot,
            zone_key,
            NO_SUBZONE_KEY,
            FALLBACK_REPORTER_ID,
            FALLBACK_REPORTER_NAME,
            timestamp=kill_ts,
            reported_by_display=FALLBACK_REPORTER_NAME,
        )
        if zone_state is None:
            # Removed by an admin while we were awaiting the network fetch.
            return FallbackSyncResult.UNKNOWN_ZONE, None

        return FallbackSyncResult.APPLIED, zone_state


def _find_poi_name(spots: object, poi_id: object) -> str | None:
    if not isinstance(spots, list):
        return None
    for spot in spots:
        if isinstance(spot, dict) and spot.get("id") == poi_id:
            name = spot.get("name")
            return name if isinstance(name, str) else None
    return None


def _parse_active_report_subzone(payload: object, zone_key: str, image_id: int) -> str | None:
    """Pure parsing step, kept separate from the network call so it's
    testable with plain dicts. Given the /region-scout payload, finds the
    region matching image_id and resolves its activeReport (if any) to one
    of our sub-zone keys via _SUBZONE_NAME_MAP. Returns None for any
    unexpected shape, no active region/report, or an unmapped spot name —
    this is an undocumented third-party endpoint that could change shape at
    any time."""
    if not isinstance(payload, dict):
        return None
    regions = payload.get("regions")
    if not isinstance(regions, list):
        return None

    for region in regions:
        if not isinstance(region, dict) or region.get("imageId") != image_id:
            continue
        active_report = region.get("activeReport")
        if not isinstance(active_report, dict):
            return None
        poi_name = _find_poi_name(region.get("spots"), active_report.get("scoutPoiId"))
        if poi_name is None:
            return None
        return _SUBZONE_NAME_MAP.get(zone_key, {}).get(poi_name)

    return None


async def fetch_found_subzone(
    server_key: str, zone_key: str, *, timeout: float = 5.0
) -> str | None:
    """Returns the sub-zone key mmopartybuilder.eu currently has an active
    "found here" report for, if any and if it maps to one of our sub-zones —
    or None on absolutely any failure (bad mapping, network error, timeout,
    non-200, unexpected JSON shape, no active report, unmapped spot name).
    Never raises."""
    target = _resolve_target(server_key, zone_key)
    if target is None:
        return None
    map_id, image_id = target
    url = f"{BASE_URL}/api/maps/{map_id}/region-scout"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001 - a third-party endpoint must never crash us
        logger.warning("Found-watch fetch failed for %s/%s: %s", server_key, zone_key, exc)
        return None

    return _parse_active_report_subzone(payload, zone_key, image_id)


async def check_and_apply_found(bot: "EliteBot", zone_key: str) -> bool:
    """Checks mmopartybuilder.eu for a currently-active "found here" report
    for this zone and, if one maps to one of our sub-zones, applies it
    exactly like a member clicking 📍 would (posts the Elite Found
    announcement, disables scout/found buttons). Returns True if applied.

    Holds the zone's lock across the whole check (consistent with
    sync_zone_from_fallback's pattern), so this never races a real member's
    📍 click on the same zone."""
    storage = bot.storage
    async with storage.zone_lock(zone_key):
        zone = storage.data["zones"].get(zone_key)
        if zone is None or zone["found_this_cycle"]:
            return False

        server_key = storage.data["config"]["fallback_server"]
        subzone_key = await fetch_found_subzone(server_key, zone_key)
        if subzone_key is None or subzone_key not in zone["subzones"]:
            return False

        result = await mark_found_and_announce_locked(bot, zone_key, subzone_key)
        return result is not None
