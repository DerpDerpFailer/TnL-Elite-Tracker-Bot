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
