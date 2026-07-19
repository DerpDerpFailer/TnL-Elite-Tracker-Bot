"""One-off installation helper: applies a fixed set of sub-zone corrections
(renames/removals/additions, worked out from the actual in-game floor names)
and copies a folder of reference map images straight into MAPS_DIR, without
going through `/elite-config map`/`submap` one attachment at a time.

This is meant to be run ONCE at install time (or once against an existing
`/data` volume to catch it up). Ongoing changes still go through the Discord
admin commands — this script is not part of the running bot.

Usage (from the repo root):
    python -m scripts.import_maps [--images-dir images] [--data-dir /data]

`--data-dir` is where elite.json/elite.json.bak/maps/ live (defaults to the
bot's real /data, but you'll usually want a local tmp dir unless this is run
from inside the deployed container/volume).
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path

from bot import domain
from bot.constants import BACKUP_FILE, DATA_DIR, DATA_FILE, MAPS_DIR
from bot.slugs import slugify
from bot.storage import Storage

# --- Sub-zone corrections, applied before anything is matched to an image --
# Worked out from the actual image filenames (see conversation): a handful of
# dungeon floors were tracked under the wrong pattern (e.g. "1B" instead of
# "B1"), some floors weren't tracked at all, and two zones had a sub-zone
# swapped for a differently-named one.

_SUBZONE_REMOVALS: list[tuple[str, str]] = [
    ("laslan-dungeon", "Syleus 1F"),
    ("laslan-dungeon", "Syleus 2F"),
    ("laslan-dungeon", "Syleus 3F"),
    ("laslan-dungeon", "Syleus 4F"),
    ("laslan-dungeon", "Syleus 5F"),
    ("stonegard-dungeon", "Sylaveth 1F"),
    ("stonegard-dungeon", "Sylaveth 2F"),
    ("nix", "Scar of Sacrifice"),
]

# (zone_key, old_display_name, new_display_name) — renamed to the "BX" pattern
_SUBZONE_RENAMES: list[tuple[str, str, str]] = [
    ("laslan-dungeon", "Shadowed Crypt 1B", "Shadowed Crypt B1"),
    ("stonegard-dungeon", "Sanctum 1B", "Sanctum B1"),
    ("talandre-dungeon", "Bercant 1B", "Bercant B1"),
    ("talandre-dungeon", "Crimson 1B", "Crimson B1"),
    ("talandre-dungeon", "Crimson 2B", "Crimson B2"),
    ("talandre-dungeon", "Crimson 3B", "Crimson B3"),
    ("talandre-dungeon", "Temple of Truth 1B", "Temple of Truth B1"),
    ("talandre-dungeon", "Temple of Truth 2B", "Temple of Truth B2"),
]

_SUBZONE_ADDITIONS: list[tuple[str, str]] = [
    ("laslan-dungeon", "Syleus B1"),
    ("laslan-dungeon", "Syleus B2"),
    ("laslan-dungeon", "Syleus B3"),
    ("laslan-dungeon", "Syleus B4"),
    ("laslan-dungeon", "Syleus B5"),
    ("laslan-dungeon", "Syleus B6"),
    ("stonegard-dungeon", "Sylaveth B1"),
    ("stonegard-dungeon", "Sylaveth B2"),
    ("talandre-dungeon", "Crimson 1F"),
    ("talandre-dungeon", "Temple of Truth 1F"),
    ("nix", "Border Zone"),
]

# --- Source image filename -> (zone_key, sub-zone display name | None) ----
# None means it's the zone-level map, not a sub-zone.
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


def apply_subzone_corrections(data) -> None:
    """Idempotent: safe to run against a fresh seed (already correct) or an
    older data file that still has the pre-correction sub-zone names."""
    for zone_key, display_name in _SUBZONE_REMOVALS:
        domain.remove_subzone(data, zone_key, slugify(display_name))

    for zone_key, old_name, new_name in _SUBZONE_RENAMES:
        zone = data["zones"][zone_key]
        old_key, new_key = slugify(old_name), slugify(new_name)
        subzone = zone["subzones"].pop(old_key, None)
        if subzone is not None:
            subzone["display_name"] = new_name
            zone["subzones"][new_key] = subzone

    for zone_key, display_name in _SUBZONE_ADDITIONS:
        zone = data["zones"][zone_key]
        subzone_key = slugify(display_name)
        if subzone_key not in zone["subzones"]:
            domain.add_subzone(data, zone_key, subzone_key, display_name)


def import_images(images_dir: Path, maps_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """Copies every image in IMAGE_MAP from images_dir to maps_dir under the
    bot's expected naming. Returns (copied, missing_sources, unmatched_files)."""
    maps_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    missing_sources: list[str] = []

    for filename, (zone_key, subzone_name) in IMAGE_MAP.items():
        source = images_dir / filename
        if not source.exists():
            missing_sources.append(filename)
            continue

        target_name = (
            f"{zone_key}.png" if subzone_name is None else f"{zone_key}__{slugify(subzone_name)}.png"
        )
        shutil.copyfile(source, maps_dir / target_name)
        copied.append(target_name)

    unmatched_files = sorted(
        f.name
        for f in images_dir.glob("*")
        if f.is_file()
        and f.suffix.lower() in (".png", ".jpg", ".jpeg")
        and f.name not in IMAGE_MAP
    )

    return copied, missing_sources, unmatched_files


def _validate_mapping(data) -> None:
    """Fails loudly if IMAGE_MAP references a zone/sub-zone that doesn't
    exist after corrections — better than silently writing an orphaned map
    file nothing will ever display."""
    errors: list[str] = []
    for filename, (zone_key, subzone_name) in IMAGE_MAP.items():
        zone = data["zones"].get(zone_key)
        if zone is None:
            errors.append(f"{filename}: unknown zone {zone_key!r}")
            continue
        if subzone_name is not None and slugify(subzone_name) not in zone["subzones"]:
            errors.append(f"{filename}: unknown sub-zone {subzone_name!r} in zone {zone_key!r}")

    if errors:
        raise SystemExit("Mapping table is out of sync with the data:\n" + "\n".join(errors))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-dir", type=Path, default=Path("images"))
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    data_file = args.data_dir / DATA_FILE.name
    backup_file = args.data_dir / BACKUP_FILE.name
    maps_dir = args.data_dir / MAPS_DIR.name

    storage = Storage(path=data_file, backup_path=backup_file)
    storage.load_or_seed()

    apply_subzone_corrections(storage.data)
    _validate_mapping(storage.data)
    await storage.save()

    copied, missing_sources, unmatched_files = import_images(args.images_dir, maps_dir)

    print(f"Applied sub-zone corrections and saved {data_file}")
    print(f"Copied {len(copied)} map image(s) into {maps_dir}")
    if missing_sources:
        print(f"Warning: {len(missing_sources)} expected source image(s) not found in {args.images_dir}:")
        for name in missing_sources:
            print(f"  - {name}")
    if unmatched_files:
        print(f"Warning: {len(unmatched_files)} image(s) in {args.images_dir} are not in IMAGE_MAP:")
        for name in unmatched_files:
            print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(main())
