"""The single perpetual status embed: building, finding/recreating, and
rate-limited updates.

`force_update` always edits (or recreates) the message immediately and is
meant to be called right after a user command changes the data. The
background task loop instead calls `flush_if_dirty`, which only performs the
edit if something marked the state dirty (e.g. an alert firing), and does so
at most once per its own tick interval — see bot/alerts.py and bot/main.py for
the actual scheduling.
"""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import tasks

from bot import strings
from bot.constants import IMMINENT_THRESHOLD_MINUTES
from bot.models import ZonePhase, zone_phase
from bot.storage import Storage

logger = logging.getLogger(__name__)


def build_status_embed(storage: Storage, now: float) -> discord.Embed:
    embed = discord.Embed(
        title=strings.STATUS_EMBED_TITLE,
        description=strings.STATUS_EMBED_DESCRIPTION,
        color=discord.Color.dark_gold(),
    )
    for zone in storage.data["zones"].values():
        phase = zone_phase(zone, now, IMMINENT_THRESHOLD_MINUTES)
        emoji = strings.PHASE_EMOJI[phase]
        if phase is ZonePhase.NO_DATA:
            line = strings.zone_line_no_data(emoji, zone["display_name"])
        else:
            line = strings.zone_line(
                emoji,
                zone["display_name"],
                int(zone["last_kill_at"]),
                int(zone["window_start"]),
                int(zone["window_end"]),
            )
        embed.add_field(name="​", value=line, inline=False)
    embed.set_footer(text=strings.status_embed_footer(int(now)))
    return embed


class PerpetualMessageManager:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._dirty = False
        self._loop: tasks.Loop | None = None

    def start(self, bot: discord.Client) -> None:
        """Starts the background loop that flushes at most once per minute."""
        if self._loop is not None:
            return

        @tasks.loop(seconds=60)
        async def loop() -> None:
            await self.flush_if_dirty(bot, time.time())

        @loop.before_loop
        async def before() -> None:
            await bot.wait_until_ready()

        self._loop = loop
        self._loop.start()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.cancel()

    def mark_dirty(self) -> None:
        self._dirty = True

    async def force_update(self, bot: discord.Client, now: float) -> None:
        async with self.storage.lock:
            await self._sync(bot, now)
            self._dirty = False

    async def flush_if_dirty(self, bot: discord.Client, now: float) -> None:
        if not self._dirty:
            return
        await self.force_update(bot, now)

    async def _sync(self, bot: discord.Client, now: float) -> None:
        config = self.storage.data["config"]
        channel_id = config["channel_id"]
        if channel_id is None:
            return

        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except discord.HTTPException as exc:
                logger.warning(strings.LOG_CHANNEL_MISSING, channel_id)
                logger.debug("fetch_channel failed: %s", exc)
                return

        embed = build_status_embed(self.storage, now)
        message_id = config["perpetual_message_id"]

        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except discord.NotFound:
                logger.warning(strings.LOG_PERPETUAL_MESSAGE_MISSING, message_id, channel_id)
            except discord.Forbidden:
                logger.warning(
                    strings.LOG_MISSING_PERMISSIONS, "edit the perpetual message", channel_id
                )
                return
            except discord.HTTPException as exc:
                logger.warning("Failed to edit perpetual message: %s", exc)
                return

        try:
            new_message = await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning(
                strings.LOG_MISSING_PERMISSIONS, "send the perpetual message", channel_id
            )
            return
        except discord.HTTPException as exc:
            logger.warning("Failed to (re)create perpetual message: %s", exc)
            return

        config["perpetual_message_id"] = new_message.id
        await self.storage.save()
