"""Static configuration constants and default seed values."""
from __future__ import annotations

from pathlib import Path
from typing import Final, TypedDict

SCHEMA_VERSION: Final[int] = 14

DATA_DIR: Final[Path] = Path("/data")
DATA_FILE: Final[Path] = DATA_DIR / "elite.json"
BACKUP_FILE: Final[Path] = DATA_DIR / "elite.json.bak"
MAPS_DIR: Final[Path] = DATA_DIR / "maps"

DEFAULT_ALERT_OFFSET_MINUTES: Final[int] = 15
DEFAULT_TIMEZONE: Final[str] = "Europe/Paris"

MAX_HISTORY_PER_ZONE: Final[int] = 50

# Emoji thresholds used by the perpetual message.
IMMINENT_THRESHOLD_MINUTES: Final[int] = 30


class DefaultZone(TypedDict):
    display_name: str
    cooldown_minutes: int


# Seeded on first boot if /data/elite.json does not exist yet.
# These are community estimates and are expected to change after weekly patches;
# admins update them via /elite-config cooldown without touching code.
DEFAULT_ZONES: Final[dict[str, DefaultZone]] = {
    "laslan": {"display_name": "Laslan", "cooldown_minutes": 4 * 60},
    "stonegard": {"display_name": "Stonegard", "cooldown_minutes": 4 * 60},
    "talandre": {"display_name": "Talandre", "cooldown_minutes": 6 * 60},
    "nix": {"display_name": "Nix", "cooldown_minutes": 6 * 60},
    "laslan-dungeon": {"display_name": "Laslan Dungeon", "cooldown_minutes": 4 * 60},
    "stonegard-dungeon": {"display_name": "Stonegard Dungeon", "cooldown_minutes": 4 * 60},
    "talandre-dungeon": {"display_name": "Talandre Dungeon", "cooldown_minutes": 6 * 60},
}

# Each region's boss can spawn at one of several named sub-zones. These are
# seeded on first boot (and backfilled by migration for existing installs)
# for the zones the guild currently tracks; admins can add/remove more later
# with /elite-config subzone-add and /elite-config subzone-remove.
DEFAULT_SUBZONES: Final[dict[str, list[str]]] = {
    "laslan": [
        "Urstella Fields",
        "Carmine Forest",
        "Nesting Grounds",
        "Fonos Basin",
        "Ruins of Turayne",
        "Purelight Hill",
        "Shattered Temple",
    ],
    "stonegard": [
        "Monolith Wastelands",
        "Abandoned Stonemason",
        "Sandworm Lair",
        "Daybreak Shore",
        "Raging Wilds",
        "Manawastes",
        "Akidu Valley",
        "Greyclaw Forest",
    ],
    "talandre": [
        "Quietis's Demesne",
        "The Great Tree",
        "Swamp of Silence",
        "Black Anvil",
        "Bercant Manor",
        "Crimson Mansion",
    ],
    "nix": [
        "Frozen Nightlands",
        "Entropic Tundra",
        "Tumgir Hollow",
        "Stillreach",
        "Scar of Sacrifice",
    ],
    "laslan-dungeon": [
        "Shadowed Crypt 1F",
        "Shadowed Crypt 2F",
        "Shadowed Crypt B1",
        "Syleus B1",
        "Syleus B2",
        "Syleus B3",
        "Syleus B4",
        "Syleus B5",
        "Syleus B6",
    ],
    "stonegard-dungeon": [
        "Sylaveth B1",
        "Sylaveth B2",
        "Ant Nest",
        "Sanctum 1F",
        "Sanctum B1",
        "Saurodoma Out",
        "Saurodoma In",
    ],
    "talandre-dungeon": [
        "Temple of Truth B1",
        "Temple of Truth B2",
        "Temple of Truth 1F",
        "Bercant 1F",
        "Bercant 2F",
        "Bercant B1",
        "Crimson B1",
        "Crimson B2",
        "Crimson B3",
    ],
}
