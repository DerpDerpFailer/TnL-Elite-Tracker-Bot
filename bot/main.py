"""Entry point: bot subclass, startup wiring, command sync, and logging setup."""
from __future__ import annotations

import asyncio
import logging
import sys
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot import strings
from bot.alerts import AlertManager
from bot.config import load_env_config
from bot.perpetual_message import PerpetualMessageManager
from bot.scouting import FoundAnnouncementView, ScoutingView, chunk_subzone_keys
from bot.storage import Storage

logger = logging.getLogger(__name__)

EXTENSIONS = (
    "bot.cogs.member_commands",
    "bot.cogs.admin_commands",
)


class EliteBot(commands.Bot):
    """Single-guild bot: no privileged intents needed since everything here is
    slash commands, and commands are synced directly to `guild_id` for instant
    registration instead of waiting on global command propagation."""

    def __init__(self, guild_id: int) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.guild_id = guild_id
        self.storage = Storage()
        self.perpetual = PerpetualMessageManager(self.storage)
        self.alerts = AlertManager(self.storage, self.perpetual)

    async def setup_hook(self) -> None:
        self.storage.load_or_seed()

        # Re-register a persistent scouting-buttons view per zone/chunk, in
        # both the pre-alert (no kill button) and spawn-due/found (with kill
        # button) shapes, so clicks on alert messages posted before this
        # restart keep routing correctly regardless of which phase they're
        # in. A zero-sub-zone zone still gets one registration for its
        # generic (no-sub-zone) kill button.
        # Also re-register one persistent FoundAnnouncementView per known
        # sub-zone, covering the 💀/🔄 buttons on any Elite Found
        # announcement still sitting unresolved from before this restart.
        for zone_key, zone in self.storage.data["zones"].items():
            chunks = chunk_subzone_keys(zone) or [[]]
            for chunk in chunks:
                self.add_view(ScoutingView(self, zone_key, chunk))
                self.add_view(ScoutingView(self, zone_key, chunk, show_kill_button=True))
            for subzone_key in zone["subzones"]:
                self.add_view(FoundAnnouncementView(self, zone_key, subzone_key))

        for extension in EXTENSIONS:
            await self.load_extension(extension)

        guild = discord.Object(id=self.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Synced application commands to guild %s", self.guild_id)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")
        # Reconcile the perpetual message immediately: find it by stored ID,
        # recreate it if missing, and replay any alert flags already set.
        await self.perpetual.force_update(self, time.time())
        self.alerts.start(self)
        self.perpetual.start(self)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # discord.http is very chatty at INFO (every request); keep it quiet.
    logging.getLogger("discord.http").setLevel(logging.WARNING)


async def main() -> None:
    configure_logging()
    env = load_env_config()

    bot = EliteBot(guild_id=env.guild_id)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        logger.exception("Unhandled application command error", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(strings.GENERIC_ERROR, ephemeral=True)
        else:
            await interaction.response.send_message(strings.GENERIC_ERROR, ephemeral=True)

    async with bot:
        await bot.start(env.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
