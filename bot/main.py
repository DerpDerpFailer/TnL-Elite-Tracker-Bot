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
from bot.default_maps import seed_default_maps
from bot.interactions import send_ephemeral
from bot.models import build_guild_config
from bot.perpetual_message import PerpetualMessageManager
from bot.scouting import FoundAnnouncementView, ScoutingView, chunk_subzone_keys
from bot.storage import Storage

logger = logging.getLogger(__name__)

EXTENSIONS = (
    "bot.cogs.member_commands",
    "bot.cogs.admin_commands",
)


class EliteBot(commands.Bot):
    """Multi-guild installable bot: no privileged intents needed since
    everything here is slash commands. Commands are synced per-guild (once
    per installed guild, on first on_ready and again on any later
    on_guild_join) rather than globally, so registration is still instant
    instead of waiting on global command propagation."""

    def __init__(self, owner_guild_id: int) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.owner_guild_id = owner_guild_id
        self.storage = Storage()
        self.perpetual = PerpetualMessageManager(self.storage)
        self.alerts = AlertManager(self.storage, self.perpetual)
        self._synced_guilds = False

    async def setup_hook(self) -> None:
        # Guild membership isn't available yet at this point (populated by
        # the READY event, which fires after this) — command sync happens in
        # on_ready instead, see below.
        self.storage.load_or_seed(owner_guild_id=self.owner_guild_id)

        copied = seed_default_maps()
        if copied:
            logger.info("Seeded %d default map image(s) into place", len(copied))

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

    async def _ensure_guild_registered(self, guild: discord.Guild) -> None:
        """Seeds an empty guilds[...] config entry for a guild we haven't
        seen before (fresh install, or one that joined while offline), so
        /elite-config channel etc. have something to write into right away."""
        async with self.storage.lock:
            guilds = self.storage.data["guilds"]
            if str(guild.id) not in guilds:
                guilds[str(guild.id)] = build_guild_config()
                await self.storage.save()

    async def _sync_commands_to(self, guild: discord.Guild) -> None:
        guild_ref = discord.Object(id=guild.id)
        self.tree.copy_global_to(guild=guild_ref)
        await self.tree.sync(guild=guild_ref)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        logger.info("Joined guild %s (%s)", guild.name, guild.id)
        await self._ensure_guild_registered(guild)
        try:
            await self._sync_commands_to(guild)
        except discord.HTTPException as exc:
            logger.warning("Failed to sync commands to newly joined guild %s: %s", guild.id, exc)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")

        for guild in self.guilds:
            await self._ensure_guild_registered(guild)

        # discord.py may call on_ready again after a reconnect; command sync
        # only needs to happen once per process, not on every reconnect.
        if not self._synced_guilds:
            for guild in self.guilds:
                try:
                    await self._sync_commands_to(guild)
                except discord.HTTPException as exc:
                    logger.warning("Failed to sync commands to guild %s: %s", guild.id, exc)
            logger.info("Synced application commands to %d guild(s)", len(self.guilds))
            self._synced_guilds = True

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

    bot = EliteBot(owner_guild_id=env.owner_guild_id)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        logger.exception("Unhandled application command error", exc_info=error)
        await send_ephemeral(interaction, strings.GENERIC_ERROR)

    async with bot:
        await bot.start(env.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
