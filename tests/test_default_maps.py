from __future__ import annotations

from bot.constants import DEFAULT_SUBZONES, DEFAULT_ZONES
from bot.default_maps import IMAGE_MAP, seed_default_maps
from bot.slugs import slugify


def test_image_map_only_references_known_zones_and_subzones():
    """Guards against the mapping table drifting out of sync with
    bot/constants.py — every entry must resolve to a real zone/sub-zone."""
    for filename, (zone_key, subzone_name) in IMAGE_MAP.items():
        assert zone_key in DEFAULT_ZONES, f"{filename}: unknown zone {zone_key!r}"
        if subzone_name is not None:
            subzone_keys = {slugify(name) for name in DEFAULT_SUBZONES.get(zone_key, [])}
            assert (
                slugify(subzone_name) in subzone_keys
            ), f"{filename}: unknown sub-zone {subzone_name!r} in zone {zone_key!r}"


def test_seed_default_maps_copies_everything_on_a_fresh_dir(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    maps_dir = tmp_path / "maps"

    for filename in IMAGE_MAP:
        (images_dir / filename).write_bytes(b"fake-png-bytes")

    copied = seed_default_maps(images_dir, maps_dir)

    assert len(copied) == len(IMAGE_MAP)
    assert (maps_dir / "laslan.png").exists()
    assert (maps_dir / "laslan__urstella-fields.png").exists()


def test_seed_default_maps_never_overwrites_an_existing_target(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()

    (images_dir / "Laslan.png").write_bytes(b"bundled-default")
    (maps_dir / "laslan.png").write_bytes(b"admin-uploaded-custom-map")

    copied = seed_default_maps(images_dir, maps_dir)

    assert "laslan.png" not in copied
    assert (maps_dir / "laslan.png").read_bytes() == b"admin-uploaded-custom-map"


def test_seed_default_maps_is_a_noop_without_a_bundled_images_dir(tmp_path):
    assert seed_default_maps(tmp_path / "does-not-exist", tmp_path / "maps") == []
