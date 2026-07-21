from __future__ import annotations

from bot import strings
from bot.alerts import AlertManager
from bot.constants import DEFAULT_SUBZONES, DEFAULT_ZONES
from bot.fallback import (
    SERVERS,
    FallbackSyncResult,
    _parse_active_report_subzone,
    _parse_region_timer_cooldown_reset,
    _resolve_target,
    _SUBZONE_NAME_MAP,
    check_and_apply_found,
    fetch_found_subzone,
    fetch_zone_kill_time,
    sync_zone_from_fallback,
)
from bot.perpetual_message import PerpetualMessageManager
from bot.slugs import slugify
from tests.fakes import FakeBot, FakeChannel


class _FakeResponse:
    def __init__(self, status: int, payload=None):
        self.status = status
        self._payload = payload

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeGetContextManager:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def get(self, url):
        return _FakeGetContextManager(self._response, self._exc)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class TestResolveTarget:
    def test_known_server_and_zone_resolves(self):
        assert _resolve_target("sacred", "laslan") == (4, 23)
        assert _resolve_target("sacred", "nix") == (4, 29)
        assert _resolve_target("sophia", "talandre-dungeon") == (9, 57)

    def test_unknown_server_returns_none(self):
        assert _resolve_target("some-other-server", "laslan") is None

    def test_unknown_zone_returns_none(self):
        assert _resolve_target("sacred", "a-custom-zone-someone-added") is None

    def test_every_default_zone_except_removed_syleus_is_covered(self):
        from bot.fallback import _ZONE_OFFSETS

        assert set(_ZONE_OFFSETS.keys()) == set(DEFAULT_ZONES.keys())


class TestParseRegionTimerCooldownReset:
    def test_extracts_the_region_timer_poi_timestamp(self):
        payload = {
            "pois": [
                {"icon": "boss", "cooldownResetAt": None},
                {"icon": "region_timer", "cooldownResetAt": "2026-07-19T18:02:09.834Z"},
            ]
        }
        result = _parse_region_timer_cooldown_reset(payload)
        assert result == 1784484129.834

    def test_missing_pois_key_returns_none(self):
        assert _parse_region_timer_cooldown_reset({}) is None

    def test_pois_not_a_list_returns_none(self):
        assert _parse_region_timer_cooldown_reset({"pois": "not-a-list"}) is None

    def test_no_region_timer_poi_returns_none(self):
        payload = {"pois": [{"icon": "boss", "cooldownResetAt": "2026-07-19T18:02:09.834Z"}]}
        assert _parse_region_timer_cooldown_reset(payload) is None

    def test_null_cooldown_reset_at_returns_none(self):
        payload = {"pois": [{"icon": "region_timer", "cooldownResetAt": None}]}
        assert _parse_region_timer_cooldown_reset(payload) is None

    def test_malformed_timestamp_returns_none(self):
        payload = {"pois": [{"icon": "region_timer", "cooldownResetAt": "not-a-date"}]}
        assert _parse_region_timer_cooldown_reset(payload) is None

    def test_payload_not_a_dict_returns_none(self):
        assert _parse_region_timer_cooldown_reset(["unexpected", "shape"]) is None
        assert _parse_region_timer_cooldown_reset(None) is None


class TestFetchZoneKillTime:
    async def test_returns_the_kill_time_on_success(self, monkeypatch):
        payload = {"pois": [{"icon": "region_timer", "cooldownResetAt": "2026-07-19T18:02:09.834Z"}]}
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(response=_FakeResponse(200, payload)),
        )
        result = await fetch_zone_kill_time("sacred", "laslan")
        assert result == 1784484129.834

    async def test_non_200_status_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(response=_FakeResponse(500)),
        )
        assert await fetch_zone_kill_time("sacred", "laslan") is None

    async def test_network_error_returns_none_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(exc=ConnectionError("boom")),
        )
        assert await fetch_zone_kill_time("sacred", "laslan") is None

    async def test_timeout_returns_none_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(exc=TimeoutError("too slow")),
        )
        assert await fetch_zone_kill_time("sacred", "laslan") is None

    async def test_unmapped_zone_returns_none_without_a_network_call(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("should not attempt a network call for an unmapped zone")

        monkeypatch.setattr("bot.fallback.aiohttp.ClientSession", _boom)
        assert await fetch_zone_kill_time("sacred", "a-custom-zone") is None


class TestSyncZoneFromFallback:
    async def test_applies_a_newer_kill(self, storage, monkeypatch):
        bot = FakeBot(storage, FakeChannel())
        storage.data["zones"]["nix"]["last_kill_at"] = 1000.0

        async def fake_fetch(server_key, zone_key, **kwargs):
            return 5000.0

        monkeypatch.setattr("bot.fallback.fetch_zone_kill_time", fake_fetch)

        result, zone_state = await sync_zone_from_fallback(bot, "nix")

        assert result is FallbackSyncResult.APPLIED
        assert zone_state["last_kill_at"] == 5000.0
        assert storage.data["zones"]["nix"]["last_kill_at"] == 5000.0

    async def test_does_not_apply_older_or_equal_data(self, storage, monkeypatch):
        bot = FakeBot(storage, FakeChannel())
        storage.data["zones"]["nix"]["last_kill_at"] = 5000.0

        async def fake_fetch(server_key, zone_key, **kwargs):
            return 1000.0

        monkeypatch.setattr("bot.fallback.fetch_zone_kill_time", fake_fetch)

        result, zone_state = await sync_zone_from_fallback(bot, "nix")

        assert result is FallbackSyncResult.NO_NEWER_DATA
        assert zone_state is None
        assert storage.data["zones"]["nix"]["last_kill_at"] == 5000.0

    async def test_first_ever_kill_is_always_applied(self, storage, monkeypatch):
        bot = FakeBot(storage, FakeChannel())
        assert storage.data["zones"]["nix"]["last_kill_at"] is None

        async def fake_fetch(server_key, zone_key, **kwargs):
            return 1000.0

        monkeypatch.setattr("bot.fallback.fetch_zone_kill_time", fake_fetch)

        result, zone_state = await sync_zone_from_fallback(bot, "nix")

        assert result is FallbackSyncResult.APPLIED
        assert zone_state["last_kill_at"] == 1000.0

    async def test_fetch_failure_is_reported_without_touching_data(self, storage, monkeypatch):
        bot = FakeBot(storage, FakeChannel())
        storage.data["zones"]["nix"]["last_kill_at"] = 1000.0

        async def fake_fetch(server_key, zone_key, **kwargs):
            return None

        monkeypatch.setattr("bot.fallback.fetch_zone_kill_time", fake_fetch)

        result, zone_state = await sync_zone_from_fallback(bot, "nix")

        assert result is FallbackSyncResult.FETCH_FAILED
        assert zone_state is None
        assert storage.data["zones"]["nix"]["last_kill_at"] == 1000.0

    async def test_unknown_zone_is_reported(self, storage):
        bot = FakeBot(storage, FakeChannel())
        result, zone_state = await sync_zone_from_fallback(bot, "no-such-zone")
        assert result is FallbackSyncResult.UNKNOWN_ZONE
        assert zone_state is None

    async def test_zone_with_no_fallback_mapping_is_reported(self, storage, monkeypatch):
        from bot import domain

        domain.add_zone(storage.data, "custom-zone", "Custom Zone", 240)
        bot = FakeBot(storage, FakeChannel())

        def _boom(*a, **k):
            raise AssertionError("should not attempt a network call for an unmapped zone")

        monkeypatch.setattr("bot.fallback.fetch_zone_kill_time", _boom)

        result, zone_state = await sync_zone_from_fallback(bot, "custom-zone")

        assert result is FallbackSyncResult.NOT_ELIGIBLE
        assert zone_state is None

    async def test_applied_kill_closes_out_scouting_and_posts_boss_killed_summary(
        self, storage, channel, monkeypatch
    ):
        bot = FakeBot(storage, channel)
        mgr = AlertManager(storage, PerpetualMessageManager(storage))
        zone = storage.data["zones"]["nix"]
        await mgr._send_pre_alert(bot, channel, "nix", zone, role_mention=None)
        primary_msg = channel.messages[zone["scouting_messages"][0]["message_id"]]
        assert primary_msg.deleted is False

        async def fake_fetch(server_key, zone_key, **kwargs):
            return 999_999.0

        monkeypatch.setattr("bot.fallback.fetch_zone_kill_time", fake_fetch)

        result, zone_state = await sync_zone_from_fallback(bot, "nix")

        assert result is FallbackSyncResult.APPLIED
        assert zone_state["last_kill_at"] == 999_999.0  # the external kill time, not time.time()
        assert primary_msg.deleted is True  # scouting message closed out, same as a real kill
        assert zone["scouting_messages"] == []

        boss_killed_embed = channel.sent[-1]["embed"]
        assert boss_killed_embed.title == "\U0001f480 Boss killed"
        values = {f.name: f.value for f in boss_killed_embed.fields}
        assert values["Zone"] == "Nix"
        assert values["Sub-zone"] == "Unknown"  # mmopartybuilder.eu is zone-wide, not per-sub-zone
        assert values["Reported by"] == "mmopartybuilder.eu (auto)"
        assert values["Next spawn"] == strings.boss_killed_next_spawn_value(int(zone_state["spawn_at"]))

    async def test_applied_kill_with_no_active_scouting_message_still_updates_data(
        self, storage, channel, monkeypatch
    ):
        # spawn_at is None by default (fresh seed) -- this is the common
        # trigger for the automatic fallback check, and there's nothing to
        # close out yet since no pre-alert has ever gone out.
        bot = FakeBot(storage, channel)

        async def fake_fetch(server_key, zone_key, **kwargs):
            return 1000.0

        monkeypatch.setattr("bot.fallback.fetch_zone_kill_time", fake_fetch)

        result, zone_state = await sync_zone_from_fallback(bot, "nix")

        assert result is FallbackSyncResult.APPLIED
        assert zone_state["last_kill_at"] == 1000.0
        assert channel.sent == []  # nothing to announce, no channel to send to


class TestSubzoneNameMap:
    def test_covers_every_zone_eligible_for_fallback(self):
        from bot.fallback import _ZONE_OFFSETS

        assert set(_SUBZONE_NAME_MAP.keys()) == set(_ZONE_OFFSETS.keys())

    def test_every_mapped_value_is_a_real_default_subzone(self):
        for zone_key, spots in _SUBZONE_NAME_MAP.items():
            valid_keys = {slugify(name) for name in DEFAULT_SUBZONES[zone_key]}
            for spot_name, subzone_key in spots.items():
                assert subzone_key in valid_keys, (
                    f"{zone_key}/{spot_name!r} maps to {subzone_key!r}, "
                    f"which isn't a default sub-zone of {zone_key}"
                )


class TestParseActiveReportSubzone:
    def _payload(self, active_report=None, spots=None, image_id=23):
        return {
            "regions": [
                {
                    "imageId": image_id,
                    "spots": spots if spots is not None else [],
                    "activeReport": active_report,
                }
            ]
        }

    def test_resolves_a_mapped_spot_name_to_our_subzone_key(self):
        payload = self._payload(
            active_report={"scoutPoiId": 5},
            spots=[{"id": 5, "name": "Urstella Fields"}],
        )
        assert _parse_active_report_subzone(payload, "laslan", 23) == "urstella-fields"

    def test_no_region_matching_image_id_returns_none(self):
        payload = self._payload(active_report={"scoutPoiId": 5}, spots=[{"id": 5, "name": "Urstella Fields"}])
        assert _parse_active_report_subzone(payload, "laslan", 999) is None

    def test_no_active_report_returns_none(self):
        payload = self._payload(active_report=None)
        assert _parse_active_report_subzone(payload, "laslan", 23) is None

    def test_unmapped_spot_name_returns_none(self):
        payload = self._payload(
            active_report={"scoutPoiId": 5},
            spots=[{"id": 5, "name": "Some Brand New Spot"}],
        )
        assert _parse_active_report_subzone(payload, "laslan", 23) is None

    def test_scout_poi_id_not_found_among_spots_returns_none(self):
        payload = self._payload(active_report={"scoutPoiId": 999}, spots=[{"id": 5, "name": "Urstella Fields"}])
        assert _parse_active_report_subzone(payload, "laslan", 23) is None

    def test_regions_not_a_list_returns_none(self):
        assert _parse_active_report_subzone({"regions": "not-a-list"}, "laslan", 23) is None

    def test_payload_not_a_dict_returns_none(self):
        assert _parse_active_report_subzone(["unexpected"], "laslan", 23) is None
        assert _parse_active_report_subzone(None, "laslan", 23) is None

    def test_active_report_not_a_dict_returns_none(self):
        payload = self._payload(active_report="not-a-dict")
        assert _parse_active_report_subzone(payload, "laslan", 23) is None

    def test_spots_not_a_list_returns_none(self):
        payload = {
            "regions": [{"imageId": 23, "spots": "not-a-list", "activeReport": {"scoutPoiId": 5}}]
        }
        assert _parse_active_report_subzone(payload, "laslan", 23) is None


class TestFetchFoundSubzone:
    async def test_returns_the_mapped_subzone_on_success(self, monkeypatch):
        payload = {
            "regions": [
                {
                    "imageId": 23,
                    "spots": [{"id": 5, "name": "Urstella Fields"}],
                    "activeReport": {"scoutPoiId": 5},
                }
            ]
        }
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(response=_FakeResponse(200, payload)),
        )
        result = await fetch_found_subzone("sacred", "laslan")
        assert result == "urstella-fields"

    async def test_non_200_status_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(response=_FakeResponse(500)),
        )
        assert await fetch_found_subzone("sacred", "laslan") is None

    async def test_network_error_returns_none_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(exc=ConnectionError("boom")),
        )
        assert await fetch_found_subzone("sacred", "laslan") is None

    async def test_timeout_returns_none_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(
            "bot.fallback.aiohttp.ClientSession",
            lambda *a, **k: _FakeSession(exc=TimeoutError("too slow")),
        )
        assert await fetch_found_subzone("sacred", "laslan") is None

    async def test_unmapped_zone_returns_none_without_a_network_call(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("should not attempt a network call for an unmapped zone")

        monkeypatch.setattr("bot.fallback.aiohttp.ClientSession", _boom)
        assert await fetch_found_subzone("sacred", "a-custom-zone") is None


class TestCheckAndApplyFound:
    async def test_applies_a_mapped_found_report_and_posts_the_announcement(
        self, storage, channel, bot, monkeypatch
    ):
        mgr = AlertManager(storage, PerpetualMessageManager(storage))
        zone = storage.data["zones"]["nix"]
        await mgr._send_pre_alert(bot, channel, "nix", zone, role_mention=None)

        async def fake_fetch(server_key, zone_key, **kwargs):
            return "scar-of-sacrifice"

        monkeypatch.setattr("bot.fallback.fetch_found_subzone", fake_fetch)

        applied = await check_and_apply_found(bot, "nix")

        assert applied is True
        assert zone["found_this_cycle"] is True
        found_embed = channel.sent[-1]["embed"]
        assert found_embed.title is not None  # Elite Found announcement went out

    async def test_returns_false_and_skips_fetch_when_already_found_this_cycle(
        self, storage, bot, monkeypatch
    ):
        storage.data["zones"]["nix"]["found_this_cycle"] = True

        def _boom(*a, **k):
            raise AssertionError("should not fetch when already found this cycle")

        monkeypatch.setattr("bot.fallback.fetch_found_subzone", _boom)

        assert await check_and_apply_found(bot, "nix") is False

    async def test_returns_false_when_fetch_finds_nothing(self, storage, bot, monkeypatch):
        async def fake_fetch(server_key, zone_key, **kwargs):
            return None

        monkeypatch.setattr("bot.fallback.fetch_found_subzone", fake_fetch)

        assert await check_and_apply_found(bot, "nix") is False
        assert storage.data["zones"]["nix"]["found_this_cycle"] is False

    async def test_returns_false_when_mapped_subzone_is_not_one_of_the_zones_subzones(
        self, storage, bot, monkeypatch
    ):
        async def fake_fetch(server_key, zone_key, **kwargs):
            return "no-such-subzone"

        monkeypatch.setattr("bot.fallback.fetch_found_subzone", fake_fetch)

        assert await check_and_apply_found(bot, "nix") is False

    async def test_unknown_zone_returns_false_without_a_fetch(self, storage, bot, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("should not fetch for an unknown zone")

        monkeypatch.setattr("bot.fallback.fetch_found_subzone", _boom)

        assert await check_and_apply_found(bot, "no-such-zone") is False


def test_servers_table_has_a_display_name_for_every_server():
    from bot.fallback import SERVER_DISPLAY_NAMES

    assert set(SERVERS.keys()) == set(SERVER_DISPLAY_NAMES.keys())
