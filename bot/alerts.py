"""Background task: checks every zone's spawn timer every 30s and fires the
pre-alert / spawn alert exactly once each, persisting the one-shot flags so a
restart never re-sends an alert that already went out.
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
from bot.scouting import ScoutingView, build_scouting_embed
from bot.storage import Storage
from bot.views import KillButtonView

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
                    due.append((key, "start"))

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
                sent = await self._send_alert(bot, channel, key, zone, kind, role_mention)
                sent_any = sent_any or sent

            if sent_any:
                self.perpetual.mark_dirty()
                await self.storage.save()

    async def _send_alert(
        self,
        bot: discord.Client,
        channel: discord.abc.Messageable,
        zone_key: str,
        zone: ZoneState,
        kind: str,
        role_mention: str | None,
    ) -> bool:
        spawn_at = int(zone["spawn_at"])

        map_path = MAPS_DIR / f"{zone_key}.png"
        file = discord.File(map_path, filename=f"{zone_key}.png") if map_path.exists() else None

        if kind == "pre":
            embed = build_scouting_embed(self.storage, zone_key)
            view: discord.ui.View | None = ScoutingView(bot, zone_key)
        else:
            embed = discord.Embed(color=discord.Color.red())
            embed.title = strings.start_alert_title(zone["display_name"])
            embed.description = strings.start_alert_description(spawn_at)
            embed.add_field(name="​", value=strings.MAP_REMINDER_NOTE, inline=False)
            if file is not None:
                embed.set_image(url=f"attachment://{zone_key}.png")
            view = KillButtonView(bot, zone_key)

        try:
            send_kwargs: dict = {"content": role_mention, "embed": embed}
            if file is not None:
                send_kwargs["file"] = file
            if view is not None:
                send_kwargs["view"] = view
            await channel.send(**send_kwargs)
        except discord.Forbidden:
            logger.warning(strings.LOG_MISSING_PERMISSIONS, "send an alert", getattr(channel, "id", "?"))
            return False
        except discord.HTTPException as exc:
            logger.warning("Failed to send alert for %s: %s", zone_key, exc)
            return False

        if kind == "pre":
            zone["pre_alert_sent"] = True
        else:
            zone["start_alert_sent"] = True
        return True
