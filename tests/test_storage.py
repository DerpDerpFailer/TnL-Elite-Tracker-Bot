from __future__ import annotations

import json

from bot.constants import SCHEMA_VERSION
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
    # v2: alert_channel_id
    assert laslan is not None and "alert_channel_id" in storage.data["config"]
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
    # v8: found_announcement_message
    assert laslan["found_announcement_message"] is None
    # v9: start_alert_sent renamed to spawn_due_marked
    assert "start_alert_sent" not in laslan
    assert laslan["spawn_due_marked"] is False


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
    storage.load_or_seed()

    nix = storage.data["zones"]["nix"]
    assert nix["last_kill_at"] == 1000.0
    assert nix["spawn_at"] == 22600.0
    assert nix["spawn_due_marked"] is True  # renamed from start_alert_sent, value preserved
    assert nix["scouting_messages"] == [
        {"channel_id": 999, "message_id": 1001, "subzone_keys": ["frozen-nightlands"]}
    ]
