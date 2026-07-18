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
from bot.models import ZoneState
from bot.perpetual_message import PerpetualMessageManager
from bot.scouting import ScoutingView, build_scouting_embed, chunk_subzone_keys
from bot.storage import Storage

logger = logging.getLogger(__name__)


class AlertManager:
    def __init__(self, storage: Storage, perpetual: PerpetualMessageManager) -> None:
        self.storage = storage
        self.perpetual = perpetual
        self._loop: tasks.Loop | None = None

    def start(self, bot: discord.Client) -> None:
        if self._loop is not None:
            return

        @tasks.loop(seconds=30)
        async def loop() -> None:
            await self.check_spawns(bot)

        @loop.before_loop
        async def before() -> None:
            await bot.wait_until_ready()

        self._loop = loop
        self._loop.start()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.cancel()

    async def check_spawns(self, bot: discord.Client) -> None:
        now = time.time()
        config = self.storage.data["config"]
        channel_id = config["alert_channel_id"] or config["channel_id"]
        if channel_id is None:
            return

        async with self.storage.lock:
            due: list[tuple[str, str]] = []
            offset_seconds = config["alert_offset_minutes"] * 60
            for key, zone in self.storage.data["zones"].items():
                if zone["spawn_at"] is None:
                    continue
                if not zone["pre_alert_sent"] and now >= zone["spawn_at"] - offset_seconds:
                    due.append((key, "pre"))
                if not zone["start_alert_sent"] and now >= zone["spawn_at"]:
                    due.append((key, "spawn_due"))

            if not due:
                return

            channel = bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except discord.HTTPException:
                    logger.warning(strings.LOG_CHANNEL_MISSING, channel_id)
                    return

            role_id = config["alert_role_id"]
            role_mention = f"<@&{role_id}>" if role_id else None

            sent_any = False
            for key, kind in due:
                zone = self.storage.data["zones"][key]
                if kind == "pre":
                    sent = await self._send_pre_alert(bot, channel, key, zone, role_mention)
                else:
                    sent = await self._mark_spawn_due(bot, key, zone)
                sent_any = sent_any or sent

            if sent_any:
                self.perpetual.mark_dirty()
                await self.storage.save()

    async def _send_pre_alert(
        self,
        bot: discord.Client,
        channel: discord.abc.Messageable,
        zone_key: str,
        zone: ZoneState,
        role_mention: str | None,
    ) -> bool:
        embed = build_scouting_embed(self.storage, zone_key)
        map_path = MAPS_DIR / f"{zone_key}.png"
        file = discord.File(map_path, filename=f"{zone_key}.png") if map_path.exists() else None

        chunks = chunk_subzone_keys(zone)
        primary_view = ScoutingView(bot, zone_key, chunks[0]) if chunks else None

        try:
            send_kwargs: dict = {"content": role_mention, "embed": embed}
            if file is not None:
                send_kwargs["file"] = file
            if primary_view is not None:
                send_kwargs["view"] = primary_view
            primary_message = await channel.send(**send_kwargs)
        except discord.Forbidden:
            logger.warning(strings.LOG_MISSING_PERMISSIONS, "send an alert", getattr(channel, "id", "?"))
            return False
        except discord.HTTPException as exc:
            logger.warning("Failed to send alert for %s: %s", zone_key, exc)
            return False

        # Always track the primary message, even with zero sub-zones (no
        # view sent), so a later spawn_due/found/kill edit can still find it.
        scouting_messages: list[dict] = [
            {
                "channel_id": getattr(channel, "id"),
                "message_id": primary_message.id,
                "subzone_keys": chunks[0] if chunks else [],
            }
        ]

        for chunk in chunks[1:]:
            continuation_view = ScoutingView(bot, zone_key, chunk)
            try:
                continuation_message = await channel.send(view=continuation_view)
            except discord.Forbidden:
                logger.warning(
                    strings.LOG_MISSING_PERMISSIONS,
                    "send a scouting continuation message",
                    getattr(channel, "id", "?"),
                )
                continue
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to send scouting continuation message for %s: %s", zone_key, exc
                )
                continue

            scouting_messages.append(
                {
                    "channel_id": getattr(channel, "id"),
                    "message_id": continuation_message.id,
                    "subzone_keys": chunk,
                }
            )

        zone["scouting_messages"] = scouting_messages
        zone["pre_alert_sent"] = True
        return True

    async def _mark_spawn_due(self, bot: discord.Client, zone_key: str, zone: ZoneState) -> bool:
        """Silently edits the zone's existing scouting message(s) to add an
        "Elite killed" button per row, instead of sending a new alert."""
        if zone["found_this_cycle"]:
            # Already further along (someone found it) — don't clobber that
            # state, just stop this from being re-checked every 30s.
            zone["start_alert_sent"] = True
            return True

        for index, ref in enumerate(zone["scouting_messages"]):
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

        zone["start_alert_sent"] = True
        return True
