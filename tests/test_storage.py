from __future__ import annotations

import asyncio
import json

from bot.constants import SCHEMA_VERSION
from bot.models import build_seed_data
from bot.slugs import slugify
from bot.storage import Storage


def test_seeds_fresh_data_when_file_missing(tmp_path):
    storage = Storage(path=tmp_path / "elite.json", backup_path=tmp_path / "elite.json.bak")
    storage.load_or_seed()

    assert storage.data["version"] == SCHEMA_VERSION
    assert "laslan" in storage.data["zones"]
    assert (tmp_path / "elite.json").exists()


async def test_save_writes_atomically_and_keeps_backup(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()  # writes the fresh seed (cooldown 240) as v1 of the file

    storage.data["zones"]["laslan"]["cooldown_minutes"] = 999
    await storage.save()

    assert json.loads(path.read_text())["zones"]["laslan"]["cooldown_minutes"] == 999
    assert backup.exists()
    # the backup should hold the version from *before* this save, not the new one
    assert json.loads(backup.read_text())["zones"]["laslan"]["cooldown_minutes"] == 240


async def test_falls_back_to_backup_when_primary_is_corrupt(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()
    storage.data["zones"]["laslan"]["cooldown_minutes"] = 111
    await storage.save()  # backup now holds the fresh seed (240), primary holds 111

    path.write_text("{not valid json at all")

    recovered = Storage(path=path, backup_path=backup)
    recovered.load_or_seed()

    assert recovered.data["zones"]["laslan"]["cooldown_minutes"] == 240


def test_seeds_fresh_when_both_files_are_corrupt(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    path.write_text("{broken")
    backup.write_text("{also broken")

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    assert storage.data["version"] == SCHEMA_VERSION
    assert storage.data["zones"]["laslan"]["cooldown_minutes"] == 240


def test_migrates_v1_data_up_to_current(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v1 = {
        "version": 1,
        "config": {
            "channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
        },
        "zones": {
            "laslan": {
                "display_name": "Laslan",
                "cooldown_minutes": 240,
                "last_kill_at": None,
                "last_kill_by": None,
                "window_start": None,
                "window_end": None,
                "pre_alert_sent": False,
                "start_alert_sent": False,
            },
        },
        "history": {"laslan": []},
        "undo": {},
    }
    path.write_text(json.dumps(old_v1))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    assert storage.data["version"] == SCHEMA_VERSION
    laslan = storage.data["zones"]["laslan"]
    # v3: known zones get their sub-zones backfilled
    assert len(laslan["subzones"]) == 7
    # v4: window_start/window_end collapsed into spawn_at
    assert "window_start" not in laslan and "window_end" not in laslan
    assert laslan["spawn_at"] is None
    # v5/v6: scouting message tracking
    assert laslan["scouting_messages"] == []
    # v7: last_kill_subzone / found_this_cycle
    assert laslan["last_kill_subzone"] is None
    assert laslan["found_this_cycle"] is False
    # v8/v15: found_announcement_message(s)
    assert laslan["found_announcement_messages"] == []
    # v9: start_alert_sent renamed to spawn_due_marked
    assert "start_alert_sent" not in laslan
    assert laslan["spawn_due_marked"] is False
    # v15: per-guild settings moved out of the shared config; with no
    # owner_guild_id passed to load_or_seed, there's nowhere to file them
    assert "channel_id" not in storage.data["config"]
    assert storage.data["guilds"] == {}
    # v11: no more standalone 'syleus' zone
    assert "syleus" not in storage.data["zones"]
    # v12: fallback-timer settings
    assert storage.data["config"]["fallback_enabled"] is False
    assert storage.data["config"]["fallback_server"] == "sacred"
    assert storage.data["config"]["fallback_threshold_minutes"] == 5


def test_migration_preserves_existing_pending_kill_state(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v6 = {
        "version": 6,
        "config": {
            "channel_id": 1,
            "alert_channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
        },
        "zones": {
            "nix": {
                "display_name": "Nix",
                "cooldown_minutes": 360,
                "last_kill_at": 1000.0,
                "last_kill_by": "tester",
                "spawn_at": 22600.0,
                "pre_alert_sent": True,
                "start_alert_sent": True,
                "subzones": {
                    "frozen-nightlands": {"display_name": "Frozen Nightlands", "scouts": []}
                },
                "scouting_messages": [
                    {
                        "channel_id": 999,
                        "message_id": 1001,
                        "subzone_keys": ["frozen-nightlands"],
                    }
                ],
            },
        },
        "history": {"nix": []},
        "undo": {},
    }
    path.write_text(json.dumps(old_v6))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed(owner_guild_id=123)

    nix = storage.data["zones"]["nix"]
    assert nix["last_kill_at"] == 1000.0
    assert nix["spawn_at"] == 22600.0
    assert nix["spawn_due_marked"] is True  # renamed from start_alert_sent, value preserved
    assert nix["scouting_messages"] == [
        {"guild_id": 123, "channel_id": 999, "message_id": 1001, "subzone_keys": ["frozen-nightlands"]}
    ]


def test_migrates_v9_dungeon_subzone_names_to_v10(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v9 = {
        "version": 9,
        "config": {
            "channel_id": None,
            "alert_channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
        },
        "zones": {
            "laslan-dungeon": {
                "display_name": "Laslan Dungeon",
                "cooldown_minutes": 240,
                "last_kill_at": None,
                "last_kill_by": None,
                "last_kill_subzone": None,
                "spawn_at": None,
                "pre_alert_sent": False,
                "spawn_due_marked": False,
                "found_this_cycle": False,
                "subzones": {
                    "shadowed-crypt-1f": {"display_name": "Shadowed Crypt 1F", "scouts": []},
                    "shadowed-crypt-1b": {"display_name": "Shadowed Crypt 1B", "scouts": [42]},
                    "syleus-1f": {"display_name": "Syleus 1F", "scouts": []},
                    "syleus-2f": {"display_name": "Syleus 2F", "scouts": []},
                },
                "scouting_messages": [],
                "found_announcement_message": None,
            },
            "nix": {
                "display_name": "Nix",
                "cooldown_minutes": 360,
                "last_kill_at": None,
                "last_kill_by": None,
                "last_kill_subzone": None,
                "spawn_at": None,
                "pre_alert_sent": False,
                "spawn_due_marked": False,
                "found_this_cycle": False,
                "subzones": {
                    "scar-of-sacrifice": {"display_name": "Scar of Sacrifice", "scouts": []},
                },
                "scouting_messages": [],
                "found_announcement_message": None,
            },
        },
        "history": {"laslan-dungeon": [], "nix": []},
        "undo": {},
    }
    path.write_text(json.dumps(old_v9))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    assert storage.data["version"] == SCHEMA_VERSION
    laslan_dungeon = storage.data["zones"]["laslan-dungeon"]
    subzones = laslan_dungeon["subzones"]
    assert "syleus-1f" not in subzones and "syleus-2f" not in subzones
    assert "shadowed-crypt-1b" not in subzones
    assert subzones["shadowed-crypt-b1"]["display_name"] == "Shadowed Crypt B1"
    assert subzones["shadowed-crypt-b1"]["scouts"] == [42]  # renamed, scouts preserved
    assert {"syleus-b1", "syleus-b2", "syleus-b3", "syleus-b4", "syleus-b5", "syleus-b6"} <= set(
        subzones
    )

    nix = storage.data["zones"]["nix"]
    # v10 replaced "Scar of Sacrifice" with "Border Zone"; v13 then renamed
    # that same sub-zone again to its correct mmopartybuilder-derived name,
    # so after the full migration chain it's "Scar of Sacrifice" once more.
    assert "border-zone" not in nix["subzones"]
    assert "scar-of-sacrifice" in nix["subzones"]


def _v9_zone(display_name: str, cooldown_minutes: int, subzone_names: list[str]) -> dict:
    return {
        "display_name": display_name,
        "cooldown_minutes": cooldown_minutes,
        "last_kill_at": None,
        "last_kill_by": None,
        "last_kill_subzone": None,
        "spawn_at": None,
        "pre_alert_sent": False,
        "spawn_due_marked": False,
        "found_this_cycle": False,
        "subzones": {
            slugify(name): {"display_name": name, "scouts": []} for name in subzone_names
        },
        "scouting_messages": [],
        "found_announcement_message": None,
    }


def test_v10_migration_converges_with_a_fresh_seed(tmp_path):
    """Guards against bot/constants.py's DEFAULT_SUBZONES drifting away from
    what the v9->v10 migration tables (_V10_SUBZONE_REMOVALS/RENAMES/
    ADDITIONS) produce for an old data file — an old install migrated up and
    a brand new install must end up with the exact same sub-zone sets for
    every zone the migration touches."""
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v9 = {
        "version": 9,
        "config": {
            "channel_id": None,
            "alert_channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
        },
        "zones": {
            "laslan-dungeon": _v9_zone(
                "Laslan Dungeon",
                240,
                [
                    "Shadowed Crypt 1F",
                    "Shadowed Crypt 2F",
                    "Shadowed Crypt 1B",
                    "Syleus 1F",
                    "Syleus 2F",
                    "Syleus 3F",
                    "Syleus 4F",
                    "Syleus 5F",
                ],
            ),
            "stonegard-dungeon": _v9_zone(
                "Stonegard Dungeon",
                240,
                [
                    "Sylaveth 1F",
                    "Sylaveth 2F",
                    "Ant Nest",
                    "Sanctum 1F",
                    "Sanctum 1B",
                    "Saurodoma Out",
                    "Saurodoma In",
                ],
            ),
            "talandre-dungeon": _v9_zone(
                "Talandre Dungeon",
                360,
                [
                    "Temple of Truth 1B",
                    "Temple of Truth 2B",
                    "Bercant 1F",
                    "Bercant 2F",
                    "Bercant 1B",
                    "Crimson 1B",
                    "Crimson 2B",
                    "Crimson 3B",
                ],
            ),
            "nix": _v9_zone(
                "Nix",
                360,
                ["Frozen Nightlands", "Scar of Sacrifice", "Entropic Tundra", "Tumgir Hollow", "Stillreach"],
            ),
            "talandre": _v9_zone(
                "Talandre",
                360,
                [
                    "Quietis Domain",
                    "The Great Tree",
                    "Swamp of Silence",
                    "Black Anvil",
                    "Bercant Manor",
                    "Crimson Mansion",
                ],
            ),
        },
        "history": {
            "laslan-dungeon": [],
            "stonegard-dungeon": [],
            "talandre-dungeon": [],
            "nix": [],
            "talandre": [],
        },
        "undo": {},
    }
    path.write_text(json.dumps(old_v9))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    fresh = build_seed_data()
    for zone_key in ("laslan-dungeon", "stonegard-dungeon", "talandre-dungeon", "nix", "talandre"):
        migrated_keys = set(storage.data["zones"][zone_key]["subzones"].keys())
        fresh_keys = set(fresh["zones"][zone_key]["subzones"].keys())
        assert migrated_keys == fresh_keys, f"{zone_key}: migrated={migrated_keys} fresh={fresh_keys}"


def test_migrates_v10_removes_orphan_syleus_zone(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v10 = {
        "version": 10,
        "config": {
            "channel_id": None,
            "alert_channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
        },
        "zones": {
            "laslan": _v9_zone("Laslan", 240, ["Urstella Fields"]),
            "syleus": _v9_zone("Syleus", 240, []),
        },
        "history": {"laslan": [], "syleus": []},
        "undo": {},
    }
    path.write_text(json.dumps(old_v10))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    assert storage.data["version"] == SCHEMA_VERSION
    assert "syleus" not in storage.data["zones"]
    assert "syleus" not in storage.data["history"]
    assert "laslan" in storage.data["zones"]  # untouched


def test_migrates_v11_backfills_fallback_config_defaults(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v11 = {
        "version": 11,
        "config": {
            "channel_id": None,
            "alert_channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
        },
        "zones": {"laslan": _v9_zone("Laslan", 240, ["Urstella Fields"])},
        "history": {"laslan": []},
        "undo": {},
    }
    path.write_text(json.dumps(old_v11))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    assert storage.data["version"] == SCHEMA_VERSION
    config = storage.data["config"]
    assert config["fallback_enabled"] is False
    assert config["fallback_server"] == "sacred"
    assert config["fallback_threshold_minutes"] == 5


def test_migrates_v12_renames_subzones_and_removes_crimson_1f(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v12 = {
        "version": 12,
        "config": {
            "channel_id": None,
            "alert_channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
            "fallback_enabled": False,
            "fallback_server": "sacred",
            "fallback_threshold_minutes": 5,
        },
        "zones": {
            "talandre": _v9_zone("Talandre", 360, ["Quietis Domain", "Black Anvil"]),
            "nix": _v9_zone("Nix", 360, ["Border Zone", "Frozen Nightlands"]),
            "talandre-dungeon": _v9_zone(
                "Talandre Dungeon", 360, ["Crimson 1F", "Crimson B1"]
            ),
        },
        "history": {"talandre": [], "nix": [], "talandre-dungeon": []},
        "undo": {},
    }
    # give the sub-zone being renamed some scout state, to check it survives
    old_v12["zones"]["talandre"]["subzones"]["quietis-domain"]["scouts"] = [99]
    path.write_text(json.dumps(old_v12))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    talandre = storage.data["zones"]["talandre"]
    assert "quietis-domain" not in talandre["subzones"]
    assert talandre["subzones"]["quietiss-demesne"]["display_name"] == "Quietis's Demesne"
    assert talandre["subzones"]["quietiss-demesne"]["scouts"] == [99]  # renamed, scouts preserved
    assert "black-anvil" in talandre["subzones"]  # untouched

    nix = storage.data["zones"]["nix"]
    assert "border-zone" not in nix["subzones"]
    assert nix["subzones"]["scar-of-sacrifice"]["display_name"] == "Scar of Sacrifice"
    assert "frozen-nightlands" in nix["subzones"]  # untouched

    talandre_dungeon = storage.data["zones"]["talandre-dungeon"]
    assert "crimson-1f" not in talandre_dungeon["subzones"]
    assert "crimson-b1" in talandre_dungeon["subzones"]  # untouched


def test_migrates_v13_backfills_found_watch_config_defaults(tmp_path):
    path = tmp_path / "elite.json"
    backup = tmp_path / "elite.json.bak"
    old_v13 = {
        "version": 13,
        "config": {
            "channel_id": None,
            "alert_channel_id": None,
            "alert_role_id": None,
            "alert_offset_minutes": 15,
            "timezone": "Europe/Paris",
            "perpetual_message_id": None,
            "admin_role_id": None,
            "fallback_enabled": False,
            "fallback_server": "sacred",
            "fallback_threshold_minutes": 5,
        },
        "zones": {"laslan": _v9_zone("Laslan", 240, ["Urstella Fields"])},
        "history": {"laslan": []},
        "undo": {},
    }
    path.write_text(json.dumps(old_v13))

    storage = Storage(path=path, backup_path=backup)
    storage.load_or_seed()

    assert storage.data["version"] == SCHEMA_VERSION
    config = storage.data["config"]
    assert config["fallback_found_watch_enabled"] is False
    assert config["fallback_found_watch_attempts"] == 10
    assert config["fallback_found_watch_slow_interval_minutes"] == 15


class TestZoneLock:
    def test_same_key_returns_the_same_lock(self, storage):
        assert storage.zone_lock("laslan") is storage.zone_lock("laslan")

    def test_different_keys_return_different_locks(self, storage):
        assert storage.zone_lock("laslan") is not storage.zone_lock("nix")

    async def test_locking_one_zone_does_not_block_another(self, storage):
        # A slow holder of laslan's lock must not delay a concurrent
        # acquisition of nix's lock — this is the whole point of splitting
        # the single global storage.lock into per-zone locks.
        events: list[str] = []

        async def hold_laslan():
            async with storage.zone_lock("laslan"):
                events.append("laslan:acquired")
                await asyncio.sleep(0.05)
                events.append("laslan:released")

        async def touch_nix():
            await asyncio.sleep(0.01)  # start after laslan has the lock
            async with storage.zone_lock("nix"):
                events.append("nix:acquired")
                events.append("nix:released")

        await asyncio.gather(hold_laslan(), touch_nix())

        # nix's whole critical section completes while laslan's is still
        # held, proving the two locks are independent.
        assert events.index("nix:released") < events.index("laslan:released")

    async def test_locking_same_zone_twice_is_serialized(self, storage):
        events: list[str] = []

        async def first():
            async with storage.zone_lock("laslan"):
                events.append("first:acquired")
                await asyncio.sleep(0.05)
                events.append("first:released")

        async def second():
            await asyncio.sleep(0.01)
            async with storage.zone_lock("laslan"):
                events.append("second:acquired")

        await asyncio.gather(first(), second())

        assert events == [
            "first:acquired",
            "first:released",
            "second:acquired",
        ]
