from __future__ import annotations

from bot.constants import DEFAULT_SUBZONES, DEFAULT_ZONES
from bot.models import build_seed_data
from bot.slugs import slugify
from scripts.import_maps import IMAGE_MAP, apply_subzone_corrections, import_images


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


def test_apply_subzone_corrections_is_idempotent():
    data = build_seed_data()
    before = {key: dict(zone["subzones"]) for key, zone in data["zones"].items()}

    apply_subzone_corrections(data)
    after_first = {key: dict(zone["subzones"]) for key, zone in data["zones"].items()}
    assert after_first == before  # a fresh seed is already fully corrected

    apply_subzone_corrections(data)
    after_second = {key: dict(zone["subzones"]) for key, zone in data["zones"].items()}
    assert after_second == after_first


def test_apply_subzone_corrections_fixes_pre_correction_data():
    data = build_seed_data()
    # Simulate an older data file seeded before the corrections existed.
    laslan_dungeon = data["zones"]["laslan-dungeon"]
    laslan_dungeon["subzones"] = {
        "shadowed-crypt-1f": {"display_name": "Shadowed Crypt 1F", "scouts": []},
        "shadowed-crypt-2f": {"display_name": "Shadowed Crypt 2F", "scouts": [42]},
        "shadowed-crypt-1b": {"display_name": "Shadowed Crypt 1B", "scouts": []},
        "syleus-1f": {"display_name": "Syleus 1F", "scouts": []},
        "syleus-2f": {"display_name": "Syleus 2F", "scouts": []},
        "syleus-3f": {"display_name": "Syleus 3F", "scouts": []},
        "syleus-4f": {"display_name": "Syleus 4F", "scouts": []},
        "syleus-5f": {"display_name": "Syleus 5F", "scouts": []},
    }

    apply_subzone_corrections(data)

    subzones = laslan_dungeon["subzones"]
    assert "syleus-1f" not in subzones
    assert set(subzones) == {
        "shadowed-crypt-1f",
        "shadowed-crypt-2f",
        "shadowed-crypt-b1",
        "syleus-b1",
        "syleus-b2",
        "syleus-b3",
        "syleus-b4",
        "syleus-b5",
        "syleus-b6",
    }
    # the rename preserves existing scout state
    assert subzones["shadowed-crypt-2f"]["scouts"] == [42]
    assert subzones["shadowed-crypt-b1"]["display_name"] == "Shadowed Crypt B1"


def test_import_images_copies_matched_files_and_reports_missing(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    maps_dir = tmp_path / "maps"

    (images_dir / "Laslan.png").write_bytes(b"fake-png-bytes")
    (images_dir / "Laslan - Urstella Fields.png").write_bytes(b"fake-png-bytes")
    (images_dir / "not-in-the-map.png").write_bytes(b"fake-png-bytes")

    copied, missing_sources, unmatched_files = import_images(images_dir, maps_dir)

    assert "laslan.png" in copied
    assert "laslan__urstella-fields.png" in copied
    assert (maps_dir / "laslan.png").read_bytes() == b"fake-png-bytes"
    assert (maps_dir / "laslan__urstella-fields.png").read_bytes() == b"fake-png-bytes"
    assert len(copied) == 2
    assert "not-in-the-map.png" in unmatched_files
    assert len(missing_sources) == len(IMAGE_MAP) - 2
