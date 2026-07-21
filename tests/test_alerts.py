from __future__ import annotations

import time

from bot import domain
from bot.alerts import FALLBACK_RETRY_SECONDS, AlertManager
from bot.fallback import FallbackSyncResult
from bot.perpetual_message import PerpetualMessageManager
from tests.fakes import FakeBot, FakeChannel


def _manager(storage) -> AlertManager:
    return AlertManager(storage, PerpetualMessageManager(storage))


class TestCheckFallback:
    async def test_skips_entirely_when_disabled(self, storage, channel, monkeypatch):
        assert storage.data["config"]["fallback_enabled"] is False
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)

        def _boom(*a, **k):
            raise AssertionError("should not be called when fallback is disabled")

        monkeypatch.setattr("bot.alerts.sync_zone_from_fallback", _boom)

        await mgr.check_spawns(bot)  # no zone has a channel configured either; must not raise

    async def test_syncs_only_stale_zones_when_enabled(self, storage, channel, monkeypatch):
        storage.data["config"]["fallback_enabled"] = True
        # give "laslan" a fresh (non-stale) timer; every other zone defaults
        # to spawn_at=None, which is always "stale"
        domain.record_kill(storage.data, "laslan", time.time(), 1, "tester")

        bot = FakeBot(storage, channel)
        mgr = _manager(storage)
        synced_zones: list[str] = []

        async def fake_sync(bot_, zone_key):
            synced_zones.append(zone_key)
            return FallbackSyncResult.NO_NEWER_DATA, None

        monkeypatch.setattr("bot.alerts.sync_zone_from_fallback", fake_sync)

        await mgr.check_spawns(bot)

        assert "laslan" not in synced_zones
        assert "nix" in synced_zones
        assert "stonegard" in synced_zones

    async def test_applied_result_marks_the_perpetual_message_dirty(self, storage, channel, monkeypatch):
        storage.data["config"]["fallback_enabled"] = True
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)

        async def fake_sync(bot_, zone_key):
            return FallbackSyncResult.APPLIED, storage.data["zones"][zone_key]

        monkeypatch.setattr("bot.alerts.sync_zone_from_fallback", fake_sync)

        assert mgr.perpetual._dirty is False
        await mgr.check_spawns(bot)
        assert mgr.perpetual._dirty is True

    async def test_respects_the_retry_interval_per_zone(self, storage, channel, monkeypatch):
        storage.data["config"]["fallback_enabled"] = True
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)
        call_count = {"n": 0}

        async def fake_sync(bot_, zone_key):
            call_count["n"] += 1
            return FallbackSyncResult.NO_NEWER_DATA, None

        monkeypatch.setattr("bot.alerts.sync_zone_from_fallback", fake_sync)

        await mgr.check_spawns(bot)
        first_call_count = call_count["n"]
        assert first_call_count > 0

        await mgr.check_spawns(bot)  # immediately again: should be rate-limited
        assert call_count["n"] == first_call_count

    async def test_runs_even_without_any_alert_channel_configured(self, storage, channel, monkeypatch):
        assert storage.data["config"]["channel_id"] is None
        assert storage.data["config"]["alert_channel_id"] is None
        storage.data["config"]["fallback_enabled"] = True
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)
        called = {"n": 0}

        async def fake_sync(bot_, zone_key):
            called["n"] += 1
            return FallbackSyncResult.NO_NEWER_DATA, None

        monkeypatch.setattr("bot.alerts.sync_zone_from_fallback", fake_sync)

        await mgr.check_spawns(bot)

        assert called["n"] > 0


def _make_zone_watchable(storage, zone_key: str, *, spawn_at: float | None = None) -> None:
    zone = storage.data["zones"][zone_key]
    zone["spawn_at"] = spawn_at if spawn_at is not None else time.time()
    zone["spawn_due_marked"] = True
    zone["found_this_cycle"] = False


class TestCheckFoundWatch:
    async def test_skips_entirely_when_disabled(self, storage, channel, monkeypatch):
        assert storage.data["config"]["fallback_found_watch_enabled"] is False
        _make_zone_watchable(storage, "nix")
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)

        def _boom(*a, **k):
            raise AssertionError("should not be called when found-watch is disabled")

        monkeypatch.setattr("bot.alerts.check_and_apply_found", _boom)

        await mgr.check_found_watch(bot)

    async def test_only_checks_zones_past_spawn_due_and_not_yet_found(self, storage, channel, monkeypatch):
        storage.data["config"]["fallback_found_watch_enabled"] = True
        _make_zone_watchable(storage, "nix")
        # "laslan" hasn't reached spawn_due yet, "stonegard" was already found this cycle
        storage.data["zones"]["laslan"]["spawn_at"] = time.time() + 999
        storage.data["zones"]["laslan"]["spawn_due_marked"] = False
        _make_zone_watchable(storage, "stonegard")
        storage.data["zones"]["stonegard"]["found_this_cycle"] = True

        bot = FakeBot(storage, channel)
        mgr = _manager(storage)
        checked: list[str] = []

        async def fake_check(bot_, zone_key):
            checked.append(zone_key)
            return False

        monkeypatch.setattr("bot.alerts.check_and_apply_found", fake_check)

        await mgr.check_found_watch(bot)

        assert checked == ["nix"]

    async def test_fast_phase_checks_every_tick_up_to_the_configured_attempts(
        self, storage, channel, monkeypatch
    ):
        storage.data["config"]["fallback_found_watch_enabled"] = True
        storage.data["config"]["fallback_found_watch_attempts"] = 3
        _make_zone_watchable(storage, "nix")
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)
        call_count = {"n": 0}

        async def fake_check(bot_, zone_key):
            call_count["n"] += 1
            return False

        monkeypatch.setattr("bot.alerts.check_and_apply_found", fake_check)

        for _ in range(3):
            await mgr.check_found_watch(bot)
        assert call_count["n"] == 3

        # 4th tick: fast-phase budget exhausted, slow interval hasn't elapsed yet
        await mgr.check_found_watch(bot)
        assert call_count["n"] == 3

    async def test_slow_phase_waits_for_the_configured_interval(self, storage, channel, monkeypatch):
        storage.data["config"]["fallback_found_watch_enabled"] = True
        storage.data["config"]["fallback_found_watch_attempts"] = 1
        storage.data["config"]["fallback_found_watch_slow_interval_minutes"] = 15
        _make_zone_watchable(storage, "nix")
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)
        call_count = {"n": 0}

        async def fake_check(bot_, zone_key):
            call_count["n"] += 1
            return False

        monkeypatch.setattr("bot.alerts.check_and_apply_found", fake_check)

        await mgr.check_found_watch(bot)
        assert call_count["n"] == 1

        # simulate the slow-phase clock having already elapsed
        mgr._found_watch_state["nix"]["last_check"] -= 15 * 60
        await mgr.check_found_watch(bot)
        assert call_count["n"] == 2

    async def test_applied_result_clears_watch_state_and_marks_perpetual_dirty(
        self, storage, channel, monkeypatch
    ):
        storage.data["config"]["fallback_found_watch_enabled"] = True
        _make_zone_watchable(storage, "nix")
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)

        async def fake_check(bot_, zone_key):
            return True

        monkeypatch.setattr("bot.alerts.check_and_apply_found", fake_check)

        assert mgr.perpetual._dirty is False
        await mgr.check_found_watch(bot)
        assert mgr.perpetual._dirty is True
        assert "nix" not in mgr._found_watch_state

    async def test_a_new_cycle_resets_the_attempt_count(self, storage, channel, monkeypatch):
        storage.data["config"]["fallback_found_watch_enabled"] = True
        storage.data["config"]["fallback_found_watch_attempts"] = 1
        _make_zone_watchable(storage, "nix", spawn_at=1000.0)
        bot = FakeBot(storage, channel)
        mgr = _manager(storage)

        async def fake_check(bot_, zone_key):
            return False

        monkeypatch.setattr("bot.alerts.check_and_apply_found", fake_check)

        await mgr.check_found_watch(bot)
        assert mgr._found_watch_state["nix"]["attempts"] == 1

        # a real kill (or admin edit) moves the zone on to its next spawn
        _make_zone_watchable(storage, "nix", spawn_at=2000.0)
        await mgr.check_found_watch(bot)
        assert mgr._found_watch_state["nix"]["attempts"] == 1  # back in the fast phase
