from __future__ import annotations

from bot import domain
from bot.models import build_seed_data


def test_slugify():
    assert domain.slugify("Urstella Fields") == "urstella-fields"
    assert domain.slugify("  Multi   Space  ") == "multi-space"
    assert domain.slugify("Weird!@# Chars") == "weird-chars"


class TestRecordKill:
    def test_computes_spawn_at_and_resets_flags(self):
        data = build_seed_data()
        zone = domain.record_kill(data, "laslan", 1000.0, 111, "Alice")
        assert zone["last_kill_at"] == 1000.0
        assert zone["last_kill_by"] == "Alice"
        assert zone["last_kill_subzone"] is None
        assert zone["spawn_at"] == 1000.0 + 240 * 60
        assert zone["pre_alert_sent"] is False
        assert zone["spawn_due_marked"] is False
        assert data["history"]["laslan"][-1]["type"] == "kill"

    def test_records_subzone(self):
        data = build_seed_data()
        zone = domain.record_kill(data, "laslan", 1000.0, 111, "Alice", "Urstella Fields")
        assert zone["last_kill_subzone"] == "Urstella Fields"

    def test_clears_scouts_and_scouting_state(self):
        data = build_seed_data()
        domain.toggle_scout(data, "laslan", "urstella-fields", 111)
        data["zones"]["laslan"]["found_this_cycle"] = True
        domain.record_kill(data, "laslan", 1000.0, 111, "Alice")
        assert data["zones"]["laslan"]["subzones"]["urstella-fields"]["scouts"] == []
        assert data["zones"]["laslan"]["found_this_cycle"] is False

    def test_caps_history_at_50(self):
        data = build_seed_data()
        for i in range(60):
            domain.record_kill(data, "laslan", float(i), 111, "Alice")
        assert len(data["history"]["laslan"]) == 50


class TestRecordNoshow:
    def test_returns_none_without_pending_spawn(self):
        data = build_seed_data()
        assert domain.record_noshow(data, "laslan", 1000.0, 111, "Alice") is None

    def test_pushes_spawn_by_cooldown(self):
        data = build_seed_data()
        domain.record_kill(data, "laslan", 1000.0, 111, "Alice")
        spawn_before = data["zones"]["laslan"]["spawn_at"]
        zone = domain.record_noshow(data, "laslan", 5000.0, 111, "Alice")
        assert zone["spawn_at"] == spawn_before + 240 * 60
        assert data["history"]["laslan"][-1]["type"] == "noshow"

    def test_does_not_touch_last_kill_info(self):
        data = build_seed_data()
        domain.record_kill(data, "laslan", 1000.0, 111, "Alice")
        domain.record_noshow(data, "laslan", 5000.0, 222, "Bob")
        assert data["zones"]["laslan"]["last_kill_by"] == "Alice"


class TestUndoLast:
    def test_nothing_to_undo(self):
        data = build_seed_data()
        assert domain.undo_last(data, "laslan") is False

    def test_restores_previous_snapshot_single_level(self):
        data = build_seed_data()
        domain.record_kill(data, "laslan", 1000.0, 111, "Alice")
        domain.record_kill(data, "laslan", 5000.0, 111, "Alice")
        assert domain.undo_last(data, "laslan") is True
        assert data["zones"]["laslan"]["last_kill_at"] == 1000.0
        # only one level of undo: nothing left after the first
        assert domain.undo_last(data, "laslan") is False

    def test_restores_history_length(self):
        data = build_seed_data()
        domain.record_kill(data, "laslan", 1000.0, 111, "Alice")
        domain.record_kill(data, "laslan", 2000.0, 111, "Alice")
        assert len(data["history"]["laslan"]) == 2
        domain.undo_last(data, "laslan")
        assert len(data["history"]["laslan"]) == 1


class TestZoneManagement:
    def test_add_zone_with_subzones(self):
        data = build_seed_data()
        domain.add_zone(data, "aldheim", "Aldheim", 300, ["Camp A", "Camp B"])
        assert data["zones"]["aldheim"]["cooldown_minutes"] == 300
        assert set(data["zones"]["aldheim"]["subzones"].keys()) == {"camp-a", "camp-b"}
        assert data["history"]["aldheim"] == []

    def test_remove_zone(self):
        data = build_seed_data()
        domain.remove_zone(data, "laslan")
        assert "laslan" not in data["zones"]
        assert "laslan" not in data["history"]

    def test_reset_zone_preserves_subzones_clears_scouts(self):
        data = build_seed_data()
        domain.record_kill(data, "laslan", 1000.0, 111, "Alice")
        domain.toggle_scout(data, "laslan", "urstella-fields", 222)
        domain.reset_zone(data, "laslan")
        zone = data["zones"]["laslan"]
        assert zone["last_kill_at"] is None
        assert "urstella-fields" in zone["subzones"]
        assert zone["subzones"]["urstella-fields"]["scouts"] == []
        assert zone["cooldown_minutes"] == 240

    def test_sync_default_zones_only_adds_missing(self):
        data = build_seed_data()
        del data["zones"]["laslan-dungeon"]
        del data["history"]["laslan-dungeon"]
        data["zones"]["laslan"]["cooldown_minutes"] = 999

        added = domain.sync_default_zones(data)

        assert added == ["Laslan Dungeon"]
        assert data["zones"]["laslan"]["cooldown_minutes"] == 999  # untouched
        assert len(data["zones"]["laslan-dungeon"]["subzones"]) == 8
        assert domain.sync_default_zones(data) == []  # idempotent


class TestSubzones:
    def test_add_and_remove(self):
        data = build_seed_data()
        domain.add_subzone(data, "laslan", "new-camp", "New Camp")
        assert data["zones"]["laslan"]["subzones"]["new-camp"]["display_name"] == "New Camp"
        domain.remove_subzone(data, "laslan", "new-camp")
        assert "new-camp" not in data["zones"]["laslan"]["subzones"]

    def test_toggle_scout_adds_then_removes(self):
        data = build_seed_data()
        assert domain.toggle_scout(data, "laslan", "urstella-fields", 111) is True
        assert data["zones"]["laslan"]["subzones"]["urstella-fields"]["scouts"] == [111]
        assert domain.toggle_scout(data, "laslan", "urstella-fields", 111) is False
        assert data["zones"]["laslan"]["subzones"]["urstella-fields"]["scouts"] == []

    def test_mark_found(self):
        data = build_seed_data()
        domain.mark_found(data, "laslan")
        assert data["zones"]["laslan"]["found_this_cycle"] is True


class TestKillIntervals:
    def test_empty_history(self):
        assert domain.kill_intervals_minutes([]) == []

    def test_computes_intervals_in_minutes_ignoring_noshows(self):
        history = [
            {"type": "kill", "timestamp": 0.0, "user_id": 1, "user_name": "a"},
            {"type": "kill", "timestamp": 3600.0, "user_id": 1, "user_name": "a"},
            {"type": "noshow", "timestamp": 5000.0, "user_id": 1, "user_name": "a"},
            {"type": "kill", "timestamp": 10800.0, "user_id": 1, "user_name": "a"},
        ]
        assert domain.kill_intervals_minutes(history) == [60.0, 120.0]

    def test_caps_at_max_intervals(self):
        history = [
            {"type": "kill", "timestamp": float(i * 60), "user_id": 1, "user_name": "a"}
            for i in range(15)
        ]
        intervals = domain.kill_intervals_minutes(history, max_intervals=10)
        assert len(intervals) == 10
