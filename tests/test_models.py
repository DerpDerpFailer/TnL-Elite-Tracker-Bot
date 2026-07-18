from __future__ import annotations

from bot.constants import DEFAULT_ZONES
from bot.models import ZonePhase, build_seed_data, zone_phase


def test_build_seed_data_has_all_default_zones():
    data = build_seed_data()
    assert set(data["zones"].keys()) == set(DEFAULT_ZONES.keys())
    assert data["zones"]["laslan"]["cooldown_minutes"] == 240
    assert data["zones"]["talandre"]["cooldown_minutes"] == 360


def test_build_seed_data_seeds_subzones_for_known_zones():
    data = build_seed_data()
    assert len(data["zones"]["laslan"]["subzones"]) == 7
    assert len(data["zones"]["stonegard"]["subzones"]) == 8
    # syleus has no community-provided sub-zone breakdown yet
    assert len(data["zones"]["syleus"]["subzones"]) == 0


class TestZonePhase:
    @staticmethod
    def _zone(spawn_at):
        return {"spawn_at": spawn_at}

    def test_no_data(self):
        zone = self._zone(None)
        assert zone_phase(zone, now=1000.0, imminent_threshold_minutes=30) == ZonePhase.NO_DATA

    def test_waiting(self):
        zone = self._zone(1000.0 + 3600)
        assert zone_phase(zone, now=1000.0, imminent_threshold_minutes=30) == ZonePhase.WAITING

    def test_imminent_at_threshold_boundary(self):
        zone = self._zone(1000.0 + 30 * 60)
        assert zone_phase(zone, now=1000.0, imminent_threshold_minutes=30) == ZonePhase.IMMINENT

    def test_just_past_imminent_threshold_is_waiting(self):
        zone = self._zone(1000.0 + 30 * 60 + 1)
        assert zone_phase(zone, now=1000.0, imminent_threshold_minutes=30) == ZonePhase.WAITING

    def test_active_exactly_at_spawn(self):
        zone = self._zone(1000.0)
        assert zone_phase(zone, now=1000.0, imminent_threshold_minutes=30) == ZonePhase.ACTIVE

    def test_active_stays_active_indefinitely_after_spawn(self):
        zone = self._zone(1000.0)
        assert zone_phase(zone, now=999999.0, imminent_threshold_minutes=30) == ZonePhase.ACTIVE
