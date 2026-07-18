"""Static configuration constants and default seed values."""
from __future__ import annotations

from pathlib import Path
from typing import Final, TypedDict

SCHEMA_VERSION: Final[int] = 9

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
    "syleus": {"display_name": "Syleus", "cooldown_minutes": 4 * 60},
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
        "Quietis Domain",
        "The Great Tree",
        "Swamp of Silence",
        "Black Anvil",
        "Bercant Manor",
        "Crimson Mansion",
    ],
    "nix": [
        "Frozen Nightlands",
        "Scar of Sacrifice",
        "Entropic Tundra",
        "Tumgir Hollow",
        "Stillreach",
    ],
    "laslan-dungeon": [
        "Shadowed Crypt 1F",
        "Shadowed Crypt 2F",
        "Shadowed Crypt 1B",
        "Syleus 1F",
        "Syleus 2F",
        "Syleus 3F",
        "Syleus 4F",
        "Syleus 5F",
    ],
    "stonegard-dungeon": [
        "Sylaveth 1F",
        "Sylaveth 2F",
        "Ant Nest",
        "Sanctum 1F",
        "Sanctum 1B",
        "Saurodoma Out",
        "Saurodoma In",
    ],
    "talandre-dungeon": [
        "Temple of Truth 1B",
        "Temple of Truth 2B",
        "Bercant 1F",
        "Bercant 2F",
        "Bercant 1B",
        "Crimson 1B",
        "Crimson 2B",
        "Crimson 3B",
    ],
}
