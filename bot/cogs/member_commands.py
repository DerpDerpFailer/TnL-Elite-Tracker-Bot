"""Member-facing slash commands: report kills/no-shows, undo, check status/stats."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot import domain, strings
from bot.autocomplete import zone_autocomplete
from bot.interactions import send_ephemeral
from bot.timeutil import get_zoneinfo, parse_zone_datetime, to_epoch

if TYPE_CHECKING:
    from bot.main import EliteBot

logger = logging.getLogger(__name__)


class MemberCommands(commands.Cog):
    def __init__(self, bot: "EliteBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="elite-killed", description="Report that an Elite boss was just killed in a zone"
    )
    @app_commands.describe(
        zone="Zone where the boss was killed",
        heure="Kill time: HH:MM (today) or DD/MM HH:MM — omit to use now",
    )
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def elite_killed(
        self, interaction: discord.Interaction, zone: str, heure: str | None = None
    ) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(zone):
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            tz = get_zoneinfo(storage.data["config"]["timezone"])
            now_dt = discord.utils.utcnow().astimezone(tz)
            try:
                kill_dt = parse_zone_datetime(heure, tz, now_dt)
            except ValueError:
                await send_ephemeral(interaction, strings.killed_invalid_time(heure or ""))
                return

            timestamp = to_epoch(kill_dt)
            zone_state = domain.record_kill(
                storage.data, zone, timestamp, interaction.user.id, str(interaction.user)
            )
            await storage.save()

        await send_ephemeral(
            interaction,
            strings.killed_confirmation(zone_state["display_name"], int(zone_state["spawn_at"])),
        )
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(
        name="elite-noshow",
        description="Report that the boss did NOT spawn at its expected time",
    )
    @app_commands.describe(zone="Zone that no-showed")
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def elite_noshow(self, interaction: discord.Interaction, zone: str) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(zone):
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            display_name = storage.data["zones"][zone]["display_name"]
            zone_state = domain.record_noshow(
                storage.data, zone, time.time(), interaction.user.id, str(interaction.user)
            )
            if zone_state is None:
                await send_ephemeral(interaction, strings.noshow_no_window(display_name))
                return
            await storage.save()

        await send_ephemeral(
            interaction,
            strings.noshow_confirmation(zone_state["display_name"], int(zone_state["spawn_at"])),
        )
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(
        name="elite-undo", description="Undo the last kill or no-show entry for a zone"
    )
    @app_commands.describe(zone="Zone to undo the last entry for")
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def elite_undo(self, interaction: discord.Interaction, zone: str) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(zone):
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            display_name = storage.data["zones"][zone]["display_name"]
            undone = domain.undo_last(storage.data, zone)
            if not undone:
                await send_ephemeral(interaction, strings.undo_nothing_to_undo(display_name))
                return
            await storage.save()

        await send_ephemeral(interaction, strings.undo_confirmation(display_name))
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(
        name="elite-status", description="Show the current respawn status of every zone"
    )
    async def elite_status(self, interaction: discord.Interaction) -> None:
        storage = self.bot.storage
        lines: list[str] = []
        for zone in storage.data["zones"].values():
            if zone["last_kill_at"] is None:
                lines.append(strings.status_row_no_data(zone["display_name"]))
            else:
                reported_by = zone["last_kill_by"] or "unknown"
                lines.append(
                    strings.status_row(
                        zone["display_name"],
                        int(zone["last_kill_at"]),
                        int(zone["spawn_at"]),
                        reported_by,
                        zone["last_kill_subzone"],
                    )
                )

        embed = discord.Embed(
            title=strings.STATUS_COMMAND_TITLE,
            description="\n".join(lines) if lines else "No zones configured.",
            color=discord.Color.blurple(),
        )
        await send_ephemeral(interaction, embed=embed)

    @app_commands.command(
        name="elite-stats",
        description="Show observed kill intervals for a zone vs. its configured cooldown",
    )
    @app_commands.describe(zone="Zone to compute stats for")
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def elite_stats(self, interaction: discord.Interaction, zone: str) -> None:
        storage = self.bot.storage
        if zone not in storage.data["zones"]:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return

        zone_state = storage.data["zones"][zone]
        history = storage.data["history"].get(zone, [])
        intervals = domain.kill_intervals_minutes(history)

        if not intervals:
            await send_ephemeral(interaction, strings.stats_no_data(zone_state["display_name"]))
            return

        lines: list[str] = []
        for i, minutes in enumerate(intervals):
            total_minutes = round(minutes)
            hours, mins = divmod(total_minutes, 60)
            lines.append(strings.stats_interval_line(i + 1, hours, mins))

        average = sum(intervals) / len(intervals)
        lines.append("")
        lines.append(strings.stats_average_line(zone_state["cooldown_minutes"], average))

        delta = average - zone_state["cooldown_minutes"]
        if abs(delta) > 15:
            lines.append(strings.stats_deviation_note(delta))

        embed = discord.Embed(
            title=strings.stats_title(zone_state["display_name"]),
            description="\n".join(lines),
            color=discord.Color.teal(),
        )
        await send_ephemeral(interaction, embed=embed)


async def setup(bot: "EliteBot") -> None:
    await bot.add_cog(MemberCommands(bot))
