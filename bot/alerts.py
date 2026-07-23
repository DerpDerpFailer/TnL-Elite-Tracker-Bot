"""Background task: checks every zone's spawn timer every 30s and fires the
pre-alert / marks the spawn as due exactly once each, persisting the one-shot
flags so a restart never re-sends an alert that already went out.

There is no separate "spawn has arrived" message: reaching spawn_at silently
edits the zone's existing scouting message(s) in place (see bot/scouting.py)
to add an "Elite killed" button per sub-zone row, instead of posting a new
embed — that's the only active notification left is the one already sent by
the pre-alert, plus whatever "Elite Found" announcement comes later.
"""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import tasks

from bot import strings
from bot.constants import MAPS_DIR
from bot.fallback import FallbackSyncResult, check_and_apply_found, sync_zone_from_fallback
from bot.models import ZoneState
from bot.perpetual_message import PerpetualMessageManager
from bot.scouting import ScoutingView, build_scouting_embed, chunk_subzone_keys, group_refs_by_guild
from bot.storage import Storage

logger = logging.getLogger(__name__)

# Minimum time between automatic fallback attempts for the same zone while it
# stays stale, so a zone nobody reports for hours doesn't hammer the (best-
# effort, unofficial) fallback endpoint every 30s tick forever.
FALLBACK_RETRY_SECONDS = 300

FOUND_WATCH_INTERVAL_SECONDS = 20


class AlertManager:
    def __init__(self, storage: Storage, perpetual: PerpetualMessageManager) -> None:
        self.storage = storage
        self.perpetual = perpetual
        self._loop: tasks.Loop | None = None
        self._found_watch_loop: tasks.Loop | None = None
        self._last_fallback_attempt: dict[str, float] = {}
        # zone_key -> {"spawn_at": float, "attempts": int, "last_check": float},
        # in-memory only (a restart just resets the count, which is harmless —
        # see check_found_watch).
        self._found_watch_state: dict[str, dict] = {}

    def start(self, bot: discord.Client) -> None:
        if self._loop is None:

            @tasks.loop(seconds=30)
            async def loop() -> None:
                await self.check_spawns(bot)

            @loop.before_loop
            async def before() -> None:
                await bot.wait_until_ready()

            self._loop = loop
            self._loop.start()

        if self._found_watch_loop is None:

            @tasks.loop(seconds=FOUND_WATCH_INTERVAL_SECONDS)
            async def found_watch_loop() -> None:
                await self.check_found_watch(bot)

            @found_watch_loop.before_loop
            async def before_found_watch() -> None:
                await bot.wait_until_ready()

            self._found_watch_loop = found_watch_loop
            self._found_watch_loop.start()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.cancel()
        if self._found_watch_loop is not None:
            self._found_watch_loop.cancel()

    async def check_spawns(self, bot: discord.Client) -> None:
        now = time.time()

        # Independent of alert-channel setup: a stale/missing timer can be
        # resynced from the fallback source even if no channel is configured.
        await self._check_fallback(bot, now)

        if not any(
            g["alert_channel_id"] or g["channel_id"] for g in self.storage.data["guilds"].values()
        ):
            return

        # Scanning for due zones touches no network/lock — this loop has no
        # `await`, so it's already atomic with respect to other coroutines
        # and doesn't need to be inside any lock.
        due: list[tuple[str, str]] = []
        offset_seconds = self.storage.data["config"]["alert_offset_minutes"] * 60
        for key, zone in self.storage.data["zones"].items():
            if zone["spawn_at"] is None:
                continue
            if not zone["pre_alert_sent"] and now >= zone["spawn_at"] - offset_seconds:
                due.append((key, "pre"))
            if not zone["spawn_due_marked"] and now >= zone["spawn_at"]:
                due.append((key, "spawn_due"))

        if not due:
            return

        # Each zone is processed under its own lock (mutate + save + the
        # network calls for that zone), so one zone's alert never blocks a
        # command or button click for another zone.
        sent_any = False
        for key, kind in due:
            async with self.storage.zone_lock(key):
                zone = self.storage.data["zones"].get(key)
                if zone is None:
                    continue  # removed mid-cycle by an admin
                if kind == "pre":
                    sent = await self._send_pre_alert(bot, key, zone)
                else:
                    sent = await self._mark_spawn_due(bot, key, zone)
                if sent:
                    await self.storage.save()
                sent_any = sent_any or sent

        if sent_any:
            self.perpetual.mark_dirty()

    async def _send_pre_alert(self, bot: discord.Client, zone_key: str, zone: ZoneState) -> bool:
        """Posts the scouting alert into every installed guild's own alert
        channel (falling back to its status channel), each getting its own
        copy of the embed/buttons and its own role ping — a guild with no
        channel configured yet is silently skipped."""
        embed = build_scouting_embed(self.storage, zone_key)
        map_path = MAPS_DIR / f"{zone_key}.png"
        chunks = chunk_subzone_keys(zone)

        scouting_messages: list[dict] = []
        for guild_id_str, guild_config in self.storage.data["guilds"].items():
            channel_id = guild_config["alert_channel_id"] or guild_config["channel_id"]
            if channel_id is None:
                continue
            guild_id = int(guild_id_str)

            channel = bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except discord.HTTPException:
                    logger.warning(strings.LOG_CHANNEL_MISSING, channel_id)
                    continue

            role_id = guild_config["alert_role_id"]
            role_mention = f"<@&{role_id}>" if role_id else None
            file = discord.File(map_path, filename=f"{zone_key}.png") if map_path.exists() else None
            primary_view = ScoutingView(bot, zone_key, chunks[0]) if chunks else None

            try:
                send_kwargs: dict = {"content": role_mention, "embed": embed}
                if file is not None:
                    send_kwargs["file"] = file
                if primary_view is not None:
                    send_kwargs["view"] = primary_view
                primary_message = await channel.send(**send_kwargs)
            except discord.Forbidden:
                logger.warning(strings.LOG_MISSING_PERMISSIONS, "send an alert", channel_id)
                continue
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to send alert for %s in guild %s: %s", zone_key, guild_id, exc
                )
                continue

            # Always track the primary message, even with zero sub-zones (no
            # view sent), so a later spawn_due/found/kill edit can still find it.
            scouting_messages.append(
                {
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "message_id": primary_message.id,
                    "subzone_keys": chunks[0] if chunks else [],
                }
            )

            for chunk in chunks[1:]:
                continuation_view = ScoutingView(bot, zone_key, chunk)
                try:
                    continuation_message = await channel.send(view=continuation_view)
                except discord.Forbidden:
                    logger.warning(
                        strings.LOG_MISSING_PERMISSIONS,
                        "send a scouting continuation message",
                        channel_id,
                    )
                    continue
                except discord.HTTPException as exc:
                    logger.warning(
                        "Failed to send scouting continuation message for %s: %s", zone_key, exc
                    )
                    continue

                scouting_messages.append(
                    {
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "message_id": continuation_message.id,
                        "subzone_keys": chunk,
                    }
                )

        if not scouting_messages:
            return False

        zone["scouting_messages"] = scouting_messages
        zone["pre_alert_sent"] = True
        return True

    async def _mark_spawn_due(self, bot: discord.Client, zone_key: str, zone: ZoneState) -> bool:
        """Silently edits the zone's existing scouting message(s) — in every
        guild that has one — to add an "Elite killed" button per row,
        instead of sending a new alert."""
        if zone["found_this_cycle"]:
            # Already further along (someone found it) — don't clobber that
            # state, just stop this from being re-checked every 30s.
            zone["spawn_due_marked"] = True
            return True

        for guild_refs in group_refs_by_guild(zone["scouting_messages"]).values():
            for index, ref in enumerate(guild_refs):
                try:
                    channel = bot.get_channel(ref["channel_id"])
                    if channel is None:
                        channel = await bot.fetch_channel(ref["channel_id"])
                    message = await channel.fetch_message(ref["message_id"])
                    view = ScoutingView(bot, zone_key, ref["subzone_keys"], show_kill_button=True)
                    if index == 0:
                        embed = build_scouting_embed(self.storage, zone_key, spawn_due=True)
                        await message.edit(embed=embed, view=view)
                    else:
                        await message.edit(view=view)
                except discord.HTTPException as exc:
                    logger.warning("Failed to mark spawn due for %s: %s", zone_key, exc)

        zone["spawn_due_marked"] = True
        return True

    async def _check_fallback(self, bot: discord.Client, now: float) -> None:
        """For each zone whose spawn timer is missing or overdue by at least
        the configured threshold, try the (best-effort, toggleable)
        mmopartybuilder.eu fallback — see bot/fallback.py. Never touches
        Discord directly and never raises: sync_zone_from_fallback already
        swallows every network/parsing failure."""
        config = self.storage.data["config"]
        if not config["fallback_enabled"]:
            return

        threshold_seconds = config["fallback_threshold_minutes"] * 60
        # Snapshot via list() — unlike the lock-free due-scan above, this loop
        # awaits between zones, so a concurrent zone-add/zone-remove could
        # otherwise mutate the dict mid-iteration.
        for zone_key, zone in list(self.storage.data["zones"].items()):
            stale = zone["spawn_at"] is None or now >= zone["spawn_at"] + threshold_seconds
            if not stale:
                continue

            last_attempt = self._last_fallback_attempt.get(zone_key, 0.0)
            if now - last_attempt < FALLBACK_RETRY_SECONDS:
                continue
            self._last_fallback_attempt[zone_key] = now

            result, _ = await sync_zone_from_fallback(bot, zone_key)
            if result is FallbackSyncResult.APPLIED:
                logger.info(
                    "Fallback sync applied a newer kill for %s from mmopartybuilder.eu", zone_key
                )
                self.perpetual.mark_dirty()

    async def check_found_watch(self, bot: discord.Client) -> None:
        """While a zone's spawn window is open and nobody has reported a
        "found" location yet (via a member's 📍 click or a real-time report),
        polls mmopartybuilder.eu's live scouting board for the same info —
        see bot/fallback.py:check_and_apply_found. Runs fast (every tick)
        for the first `fallback_found_watch_attempts` checks, since that's
        when a member is most likely to be actively scouting; after that it
        backs off to once every `fallback_found_watch_slow_interval_minutes`,
        since quiet hours (e.g. early morning) can otherwise mean nobody
        reports for a long time and there's no point hammering the endpoint
        every 20s waiting for that."""
        config = self.storage.data["config"]
        if not config["fallback_found_watch_enabled"]:
            return

        now = time.time()
        attempts_limit = config["fallback_found_watch_attempts"]
        slow_interval_seconds = config["fallback_found_watch_slow_interval_minutes"] * 60

        # Snapshot via list() — this loop awaits between zones, so a
        # concurrent zone-add/zone-remove could otherwise mutate the dict
        # mid-iteration (same reasoning as _check_fallback above).
        for zone_key, zone in list(self.storage.data["zones"].items()):
            if not zone["spawn_due_marked"] or zone["found_this_cycle"] or zone["spawn_at"] is None:
                self._found_watch_state.pop(zone_key, None)
                continue

            state = self._found_watch_state.get(zone_key)
            if state is None or state["spawn_at"] != zone["spawn_at"]:
                state = {"spawn_at": zone["spawn_at"], "attempts": 0, "last_check": 0.0}
                self._found_watch_state[zone_key] = state

            in_fast_phase = state["attempts"] < attempts_limit
            if not in_fast_phase and now - state["last_check"] < slow_interval_seconds:
                continue

            state["attempts"] += 1
            state["last_check"] = now

            applied = await check_and_apply_found(bot, zone_key)
            if applied:
                logger.info(
                    "Found-watch applied a live location report for %s from mmopartybuilder.eu",
                    zone_key,
                )
                self._found_watch_state.pop(zone_key, None)
                self.perpetual.mark_dirty()
