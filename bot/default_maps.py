"""Bundled default map images (the top-level `images/` folder, shipped in the
Docker image — see Dockerfile's `COPY images ./images`).

`seed_default_maps()` runs on every bot startup and copies any bundled image
whose target doesn't already exist in MAPS_DIR. It never overwrites a file
that's already there, so an admin's `/elite-config map`/`submap` upload
always wins over the bundled default, and a brand new zone's bundled map
added in a later update still gets picked up on the next restart. This is
what makes a fresh install (or a fresh /data volume on another server) come
up fully pre-configured with zone/sub-zone maps, no manual step required.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from bot.constants import MAPS_DIR
from bot.slugs import slugify

logger = logging.getLogger(__name__)

DEFAULT_IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"

# Source image filename (relative to DEFAULT_IMAGES_DIR) -> (zone_key,
# sub-zone display name | None). None means it's the zone-level map.
IMAGE_MAP: dict[str, tuple[str, str | None]] = {
    "Laslan.png": ("laslan", None),
    "Laslan - Urstella Fields.png": ("laslan", "Urstella Fields"),
    "Laslan - Carmine Forest.png": ("laslan", "Carmine Forest"),
    "Laslan - Nesting Grounds.png": ("laslan", "Nesting Grounds"),
    "Laslan - Fonos Basin.png": ("laslan", "Fonos Basin"),
    "Laslan - Ruins of Turayne.png": ("laslan", "Ruins of Turayne"),
    "Laslan - Purelight Hill.png": ("laslan", "Purelight Hill"),
    "Laslan - Shattered Temple.png": ("laslan", "Shattered Temple"),
    "Laslan Dungeon.png": ("laslan-dungeon", None),
    "Laslan Dungeon - Shadowed Crypt 1F.png": ("laslan-dungeon", "Shadowed Crypt 1F"),
    "Laslan Dungeon - Shadowed Crypt 2F.png": ("laslan-dungeon", "Shadowed Crypt 2F"),
    "Laslan Dungeon - Shadowed Crypt B1.png": ("laslan-dungeon", "Shadowed Crypt B1"),
    "Laslan Dungeon - Syleus B1.png": ("laslan-dungeon", "Syleus B1"),
    "Laslan Dungeon - Syleus B2.png": ("laslan-dungeon", "Syleus B2"),
    "Laslan Dungeon - Syleus B3.png": ("laslan-dungeon", "Syleus B3"),
    "Laslan Dungeon - Syleus B4.png": ("laslan-dungeon", "Syleus B4"),
    "Laslan Dungeon - Syleus B5.png": ("laslan-dungeon", "Syleus B5"),
    "Laslan Dungeon - Syleus B6.png": ("laslan-dungeon", "Syleus B6"),
    "Nix.png": ("nix", None),
    "Nix - Frozen Nightlands.png": ("nix", "Frozen Nightlands"),
    "Nix - Entropic Tundra.png": ("nix", "Entropic Tundra"),
    "Nix - Tumgir Hollow.png": ("nix", "Tumgir Hollow"),
    "Nix - Stillreach.png": ("nix", "Stillreach"),
    "Nix - Border Zone.png": ("nix", "Border Zone"),
    "Stonegard.png": ("stonegard", None),
    "Stonegard - Monolith Wastelands.png": ("stonegard", "Monolith Wastelands"),
    "Stonegard - Abandoned Stonemason.png": ("stonegard", "Abandoned Stonemason"),
    "Stonegard - Sandworm Lair.png": ("stonegard", "Sandworm Lair"),
    "Stonegard - Daybreak Shore.png": ("stonegard", "Daybreak Shore"),
    "Stonegard - Raging Wilds.png": ("stonegard", "Raging Wilds"),
    "Stonegard - Manawastes.png": ("stonegard", "Manawastes"),
    "Stonegard - Akidu Valley.png": ("stonegard", "Akidu Valley"),
    "Stonegard - Greyclaw Forest.png": ("stonegard", "Greyclaw Forest"),
    "Stonegard Dungeon.png": ("stonegard-dungeon", None),
    "Stonegard Dungeon - Ant Nest.png": ("stonegard-dungeon", "Ant Nest"),
    "Stonegard Dungeon - Sanctum 1F.png": ("stonegard-dungeon", "Sanctum 1F"),
    "Stonegard Dungeon - Sanctum B1.png": ("stonegard-dungeon", "Sanctum B1"),
    "Stonegard Dungeon - Saurodoma Out.png": ("stonegard-dungeon", "Saurodoma Out"),
    "Stonegard Dungeon - Saurodoma In.png": ("stonegard-dungeon", "Saurodoma In"),
    "Stonegard Dungeon - Sylaveth B1.png": ("stonegard-dungeon", "Sylaveth B1"),
    "Stonegard Dungeon - Sylaveth B2.png": ("stonegard-dungeon", "Sylaveth B2"),
    "Talandre.png": ("talandre", None),
    "Talandre - Quietis Domain.png": ("talandre", "Quietis Domain"),
    "Talandre - The Great Tree.png": ("talandre", "The Great Tree"),
    "Talandre - Swamp of Silence.png": ("talandre", "Swamp of Silence"),
    "Talandre - Black Anvil.png": ("talandre", "Black Anvil"),
    "Talandre - Bercant.png": ("talandre", "Bercant Manor"),
    "Talandre - Crimson.png": ("talandre", "Crimson Mansion"),
    "Talandre Dungeon.png": ("talandre-dungeon", None),
    "Talandre Dungeon - Bercant 1F.png": ("talandre-dungeon", "Bercant 1F"),
    "Talandre Dungeon - Bercant 2F.png": ("talandre-dungeon", "Bercant 2F"),
    "Talandre Dungeon - Bercant B1.png": ("talandre-dungeon", "Bercant B1"),
    "Talandre Dungeon - Crimson 1F.png": ("talandre-dungeon", "Crimson 1F"),
    "Talandre Dungeon - Crimson B1.png": ("talandre-dungeon", "Crimson B1"),
    "Talandre Dungeon - Crimson B2.png": ("talandre-dungeon", "Crimson B2"),
    "Talandre Dungeon - Crimson B3.png": ("talandre-dungeon", "Crimson B3"),
    "Talandre Dungeon - Temple 1F.png": ("talandre-dungeon", "Temple of Truth 1F"),
    "Talandre Dungeon - Temple B1.png": ("talandre-dungeon", "Temple of Truth B1"),
    "Talandre Dungeon - Temple B2.png": ("talandre-dungeon", "Temple of Truth B2"),
}


def seed_default_maps(
    images_dir: Path = DEFAULT_IMAGES_DIR, maps_dir: Path = MAPS_DIR
) -> list[str]:
    """Copies every bundled image whose target isn't already in maps_dir.
    Returns the target filenames actually copied (empty on every boot after
    the first, once everything's already in place)."""
    if not images_dir.exists():
        return []

    maps_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    for filename, (zone_key, subzone_name) in IMAGE_MAP.items():
        target_name = (
            f"{zone_key}.png" if subzone_name is None else f"{zone_key}__{slugify(subzone_name)}.png"
        )
        target = maps_dir / target_name
        if target.exists():
            continue

        source = images_dir / filename
        if not source.exists():
            logger.warning("Bundled default map %s is missing from %s", filename, images_dir)
            continue

        shutil.copyfile(source, target)
        copied.append(target_name)

    return copied
