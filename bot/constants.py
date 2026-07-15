"""Static configuration constants and default seed values."""
from __future__ import annotations

from pathlib import Path
from typing import Final, TypedDict

SCHEMA_VERSION: Final[int] = 2

DATA_DIR: Final[Path] = Path("/data")
DATA_FILE: Final[Path] = DATA_DIR / "elite.json"
BACKUP_FILE: Final[Path] = DATA_DIR / "elite.json.bak"
MAPS_DIR: Final[Path] = DATA_DIR / "maps"

SPAWN_WINDOW_MINUTES: Final[int] = 7
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
}
