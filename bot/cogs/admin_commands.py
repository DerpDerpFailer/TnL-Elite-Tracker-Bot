"""Admin-only /elite-config command group.

Gated two ways: `default_permissions=Manage Server` (Discord's own default,
which guild admins can further customize per-role from Server Settings ->
Integrations), plus a code-level `interaction_check` that also allows the
guild-configured admin role stored in elite.json (see `admin-role` below) —
this is what "un rôle admin configurable" refers to in the spec, since it
must be settable from somewhere.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfoNotFoundError

import discord
from discord import app_commands

from bot import domain, strings
from bot.autocomplete import subzone_autocomplete, zone_autocomplete
from bot.constants import MAPS_DIR
from bot.interactions import send_ephemeral
from bot.timeutil import get_zoneinfo, parse_duration_to_minutes

if TYPE_CHECKING:
    from bot.main import EliteBot

logger = logging.getLogger(__name__)

# Discord caps both embeds and file attachments at 10 per message.
_MAX_PREVIEW_EMBEDS_PER_MESSAGE = 10


def _has_admin_access(interaction: discord.Interaction, bot: "EliteBot") -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild:
        return True
    admin_role_id = bot.storage.data["config"]["admin_role_id"]
    return admin_role_id is not None and any(role.id == admin_role_id for role in member.roles)


class AdminConfigGroup(app_commands.Group):
    def __init__(self, bot: "EliteBot") -> None:
        super().__init__(
            name="elite-config",
            description="Admin configuration for the Elite boss tracker",
            default_permissions=discord.Permissions(manage_guild=True),
            guild_only=True,
        )
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if _has_admin_access(interaction, self.bot):
            return True
        await send_ephemeral(interaction, strings.NO_PERMISSION)
        return False

    @app_commands.command(name="cooldown", description="Set the respawn cooldown for a zone")
    @app_commands.describe(zone="Zone to update", duree="Cooldown duration, e.g. '4h' or '5h30'")
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def cooldown(self, interaction: discord.Interaction, zone: str, duree: str) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(zone):
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return
            try:
                minutes = parse_duration_to_minutes(duree)
            except ValueError:
                await send_ephemeral(interaction, strings.config_invalid_duration(duree))
                return
            storage.data["zones"][zone]["cooldown_minutes"] = minutes
            display_name = storage.data["zones"][zone]["display_name"]
            await storage.save()

        await send_ephemeral(interaction, strings.config_cooldown_updated(display_name, minutes))
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(
        name="channel", description="Set the channel for the perpetual status message"
    )
    @app_commands.describe(canal="Channel to post/update the status message in")
    async def channel(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        storage = self.bot.storage
        async with storage.lock:
            storage.data["config"]["channel_id"] = canal.id
            storage.data["config"]["perpetual_message_id"] = None
            await storage.save()

        await send_ephemeral(interaction, strings.config_channel_updated(canal.mention))
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(
        name="alert-channel",
        description="Set (or clear) a separate channel for spawn alerts",
    )
    @app_commands.describe(
        canal="Channel for pre-alert/spawn-open alerts; omit to use the status channel instead"
    )
    async def alert_channel(
        self, interaction: discord.Interaction, canal: discord.TextChannel | None = None
    ) -> None:
        storage = self.bot.storage
        async with storage.lock:
            storage.data["config"]["alert_channel_id"] = canal.id if canal else None
            await storage.save()

        if canal is not None:
            await send_ephemeral(interaction, strings.config_alert_channel_updated(canal.mention))
        else:
            await send_ephemeral(interaction, strings.config_alert_channel_cleared())

    @app_commands.command(
        name="alert-role", description="Set (or clear) the role pinged in alerts"
    )
    @app_commands.describe(role="Role to mention in alerts; omit to clear (no ping)")
    async def alert_role(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ) -> None:
        storage = self.bot.storage
        async with storage.lock:
            storage.data["config"]["alert_role_id"] = role.id if role else None
            await storage.save()

        if role is not None:
            await send_ephemeral(interaction, strings.config_alert_role_updated(role.mention))
        else:
            await send_ephemeral(interaction, strings.config_alert_role_cleared())

    @app_commands.command(
        name="admin-role", description="Set (or clear) the role allowed to use /elite-config"
    )
    @app_commands.describe(role="Role allowed to manage the tracker; omit to clear")
    async def admin_role(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ) -> None:
        storage = self.bot.storage
        async with storage.lock:
            storage.data["config"]["admin_role_id"] = role.id if role else None
            await storage.save()

        if role is not None:
            await send_ephemeral(interaction, strings.config_admin_role_updated(role.mention))
        else:
            await send_ephemeral(interaction, strings.config_admin_role_cleared())

    @app_commands.command(
        name="alert-offset", description="Set the pre-alert delay before a window opens"
    )
    @app_commands.describe(minutes="Minutes before the window opens to send a pre-alert")
    async def alert_offset(
        self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 180]
    ) -> None:
        storage = self.bot.storage
        async with storage.lock:
            storage.data["config"]["alert_offset_minutes"] = minutes
            await storage.save()

        await send_ephemeral(interaction, strings.config_alert_offset_updated(minutes))

    @app_commands.command(
        name="timezone", description="Set the timezone used to interpret manual kill times"
    )
    @app_commands.describe(tz="IANA timezone name, e.g. Europe/Paris")
    async def timezone(self, interaction: discord.Interaction, tz: str) -> None:
        try:
            get_zoneinfo(tz)
        except ZoneInfoNotFoundError:
            await send_ephemeral(interaction, strings.config_timezone_invalid(tz))
            return

        storage = self.bot.storage
        async with storage.lock:
            storage.data["config"]["timezone"] = tz
            await storage.save()

        await send_ephemeral(interaction, strings.config_timezone_updated(tz))

    @app_commands.command(name="map", description="Upload/replace the map image for a zone")
    @app_commands.describe(
        zone="Zone to update the map for",
        image="PNG or JPG map image with spawn points marked",
    )
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def set_map(
        self, interaction: discord.Interaction, zone: str, image: discord.Attachment
    ) -> None:
        storage = self.bot.storage
        if zone not in storage.data["zones"]:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return

        content_type = (image.content_type or "").lower()
        if not (content_type.startswith("image/png") or content_type.startswith("image/jpeg")):
            await send_ephemeral(interaction, strings.config_map_invalid_type())
            return

        MAPS_DIR.mkdir(parents=True, exist_ok=True)
        await image.save(MAPS_DIR / f"{zone}.png")

        display_name = storage.data["zones"][zone]["display_name"]
        await send_ephemeral(interaction, strings.config_map_updated(display_name))

    @app_commands.command(name="zone-add", description="Add a new zone to track")
    @app_commands.describe(
        nom="Display name for the new zone", cooldown="Cooldown duration, e.g. '4h' or '5h30'"
    )
    async def zone_add(self, interaction: discord.Interaction, nom: str, cooldown: str) -> None:
        storage = self.bot.storage
        async with storage.lock:
            try:
                minutes = parse_duration_to_minutes(cooldown)
            except ValueError:
                await send_ephemeral(interaction, strings.config_invalid_duration(cooldown))
                return

            key = domain.slugify(nom)
            if key in storage.data["zones"]:
                existing_name = storage.data["zones"][key]["display_name"]
                await send_ephemeral(interaction, strings.config_zone_already_exists(existing_name))
                return

            domain.add_zone(storage.data, key, nom, minutes)
            await storage.save()

        await send_ephemeral(interaction, strings.config_zone_added(nom, minutes))
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(
        name="sync-zones",
        description="Add any built-in default zone (with its sub-zones) missing from this server",
    )
    async def sync_zones(self, interaction: discord.Interaction) -> None:
        storage = self.bot.storage
        async with storage.lock:
            added = domain.sync_default_zones(storage.data)
            if added:
                await storage.save()

        if added:
            await send_ephemeral(interaction, strings.config_sync_zones_added(added))
            await self.bot.perpetual.force_update(self.bot, time.time())
        else:
            await send_ephemeral(interaction, strings.config_sync_zones_up_to_date())

    @app_commands.command(name="zone-remove", description="Remove a tracked zone and its history")
    @app_commands.describe(zone="Zone to remove")
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def zone_remove(self, interaction: discord.Interaction, zone: str) -> None:
        storage = self.bot.storage
        async with storage.lock:
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            display_name = storage.data["zones"][zone]["display_name"]
            subzone_keys = list(storage.data["zones"][zone]["subzones"].keys())
            domain.remove_zone(storage.data, zone)
            await storage.save()

        map_path = MAPS_DIR / f"{zone}.png"
        if map_path.exists():
            map_path.unlink()
        for subzone_key in subzone_keys:
            submap_path = MAPS_DIR / f"{zone}__{subzone_key}.png"
            if submap_path.exists():
                submap_path.unlink()

        await send_ephemeral(interaction, strings.config_zone_removed(display_name))
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(
        name="zone-reset",
        description="Clear a zone's last kill, current window and history (keeps cooldown and map)",
    )
    @app_commands.describe(zone="Zone to reset")
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def zone_reset(self, interaction: discord.Interaction, zone: str) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(zone):
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            display_name = storage.data["zones"][zone]["display_name"]
            domain.reset_zone(storage.data, zone)
            await storage.save()

        await send_ephemeral(interaction, strings.config_zone_reset(display_name))
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(name="subzone-add", description="Add a scouting sub-zone to a zone")
    @app_commands.describe(
        zone="Zone to add the sub-zone to", nom="Display name for the new sub-zone"
    )
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def subzone_add(self, interaction: discord.Interaction, zone: str, nom: str) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(zone):
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            zone_display_name = storage.data["zones"][zone]["display_name"]
            subzone_key = domain.slugify(nom)
            if subzone_key in storage.data["zones"][zone]["subzones"]:
                existing_name = storage.data["zones"][zone]["subzones"][subzone_key][
                    "display_name"
                ]
                await send_ephemeral(
                    interaction, strings.config_subzone_already_exists(zone_display_name, existing_name)
                )
                return

            domain.add_subzone(storage.data, zone, subzone_key, nom)
            await storage.save()

        await send_ephemeral(interaction, strings.config_subzone_added(zone_display_name, nom))

    @app_commands.command(
        name="subzone-remove", description="Remove a scouting sub-zone from a zone"
    )
    @app_commands.describe(zone="Zone the sub-zone belongs to", subzone="Sub-zone to remove")
    @app_commands.autocomplete(zone=zone_autocomplete, subzone=subzone_autocomplete)
    async def subzone_remove(
        self, interaction: discord.Interaction, zone: str, subzone: str
    ) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(zone):
            if zone not in storage.data["zones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return
            if subzone not in storage.data["zones"][zone]["subzones"]:
                await send_ephemeral(interaction, strings.config_subzone_not_found())
                return

            zone_display_name = storage.data["zones"][zone]["display_name"]
            subzone_display_name = storage.data["zones"][zone]["subzones"][subzone][
                "display_name"
            ]
            domain.remove_subzone(storage.data, zone, subzone)
            await storage.save()

        submap_path = MAPS_DIR / f"{zone}__{subzone}.png"
        if submap_path.exists():
            submap_path.unlink()

        await send_ephemeral(
            interaction, strings.config_subzone_removed(zone_display_name, subzone_display_name)
        )

    @app_commands.command(
        name="submap", description="Upload/replace the map image for a specific sub-zone"
    )
    @app_commands.describe(
        zone="Zone the sub-zone belongs to",
        subzone="Sub-zone to update the map for",
        image="PNG or JPG map image, e.g. a close-up crop with the spawn pin marked",
    )
    @app_commands.autocomplete(zone=zone_autocomplete, subzone=subzone_autocomplete)
    async def submap(
        self,
        interaction: discord.Interaction,
        zone: str,
        subzone: str,
        image: discord.Attachment,
    ) -> None:
        storage = self.bot.storage
        if zone not in storage.data["zones"]:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return
        if subzone not in storage.data["zones"][zone]["subzones"]:
            await send_ephemeral(interaction, strings.config_subzone_not_found())
            return

        content_type = (image.content_type or "").lower()
        if not (content_type.startswith("image/png") or content_type.startswith("image/jpeg")):
            await send_ephemeral(interaction, strings.config_map_invalid_type())
            return

        MAPS_DIR.mkdir(parents=True, exist_ok=True)
        await image.save(MAPS_DIR / f"{zone}__{subzone}.png")

        zone_display_name = storage.data["zones"][zone]["display_name"]
        subzone_display_name = storage.data["zones"][zone]["subzones"][subzone]["display_name"]
        await send_ephemeral(
            interaction, strings.config_submap_updated(zone_display_name, subzone_display_name)
        )

    @app_commands.command(
        name="preview-zone",
        description="Show every map image for a zone: its own map plus every sub-zone's",
    )
    @app_commands.describe(zone="Zone to preview the maps for")
    @app_commands.autocomplete(zone=zone_autocomplete)
    async def preview_zone(self, interaction: discord.Interaction, zone: str) -> None:
        storage = self.bot.storage
        if zone not in storage.data["zones"]:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return

        zone_state = storage.data["zones"][zone]
        entries: list[tuple[str, Path]] = [(zone_state["display_name"], MAPS_DIR / f"{zone}.png")]
        for subzone_key, subzone in zone_state["subzones"].items():
            entries.append((subzone["display_name"], MAPS_DIR / f"{zone}__{subzone_key}.png"))

        header = strings.preview_zone_header(zone_state["display_name"])
        for chunk_start in range(0, len(entries), _MAX_PREVIEW_EMBEDS_PER_MESSAGE):
            chunk = entries[chunk_start : chunk_start + _MAX_PREVIEW_EMBEDS_PER_MESSAGE]
            embeds: list[discord.Embed] = []
            files: list[discord.File] = []
            for title, map_path in chunk:
                embed = discord.Embed(title=title, color=discord.Color.blurple())
                if map_path.exists():
                    embed.set_image(url=f"attachment://{map_path.name}")
                    files.append(discord.File(map_path, filename=map_path.name))
                else:
                    embed.description = strings.MAP_NOT_UPLOADED_NOTE
                embeds.append(embed)

            await send_ephemeral(
                interaction,
                header if chunk_start == 0 else None,
                embeds=embeds,
                files=files,
            )

    @app_commands.command(
        name="preview-map", description="Show the map image for a zone or one specific sub-zone"
    )
    @app_commands.describe(
        zone="Zone to preview", subzone="Sub-zone to preview; omit for the zone-level map"
    )
    @app_commands.autocomplete(zone=zone_autocomplete, subzone=subzone_autocomplete)
    async def preview_map(
        self, interaction: discord.Interaction, zone: str, subzone: str | None = None
    ) -> None:
        storage = self.bot.storage
        if zone not in storage.data["zones"]:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return

        zone_state = storage.data["zones"][zone]
        if subzone is None:
            title = zone_state["display_name"]
            map_path = MAPS_DIR / f"{zone}.png"
        else:
            if subzone not in zone_state["subzones"]:
                await send_ephemeral(interaction, strings.config_subzone_not_found())
                return
            title = zone_state["subzones"][subzone]["display_name"]
            map_path = MAPS_DIR / f"{zone}__{subzone}.png"

        if not map_path.exists():
            await send_ephemeral(interaction, strings.config_map_missing(title))
            return

        embed = discord.Embed(title=title, color=discord.Color.blurple())
        embed.set_image(url=f"attachment://{map_path.name}")
        file = discord.File(map_path, filename=map_path.name)
        await send_ephemeral(interaction, embed=embed, file=file)

    @app_commands.command(
        name="repost",
        description="Recreate the perpetual status message if it was deleted, or force a refresh",
    )
    async def repost(self, interaction: discord.Interaction) -> None:
        if self.bot.storage.data["config"]["channel_id"] is None:
            await send_ephemeral(interaction, strings.config_repost_no_channel())
            return

        await send_ephemeral(interaction, strings.config_repost_confirmation())
        await self.bot.perpetual.force_update(self.bot, time.time())

    @app_commands.command(name="show", description="Show the current tracker configuration")
    async def show(self, interaction: discord.Interaction) -> None:
        storage = self.bot.storage
        config = storage.data["config"]

        channel_mention = f"<#{config['channel_id']}>" if config["channel_id"] else None
        alert_channel_mention = (
            f"<#{config['alert_channel_id']}>" if config["alert_channel_id"] else None
        )
        alert_role_mention = f"<@&{config['alert_role_id']}>" if config["alert_role_id"] else None
        admin_role_mention = f"<@&{config['admin_role_id']}>" if config["admin_role_id"] else None

        general_lines = [
            strings.config_show_channel_line(channel_mention),
            strings.config_show_alert_channel_line(alert_channel_mention),
            strings.config_show_alert_role_line(alert_role_mention),
            strings.config_show_admin_role_line(admin_role_mention),
            strings.config_show_alert_offset_line(config["alert_offset_minutes"]),
            strings.config_show_timezone_line(config["timezone"]),
        ]

        zone_lines = [
            strings.config_show_zone_line(
                zone["display_name"],
                zone["cooldown_minutes"],
                (MAPS_DIR / f"{key}.png").exists(),
                len(zone["subzones"]),
            )
            for key, zone in storage.data["zones"].items()
        ]

        embed = discord.Embed(title=strings.CONFIG_SHOW_TITLE, color=discord.Color.blurple())
        embed.add_field(
            name=strings.CONFIG_SHOW_GENERAL_FIELD, value="\n".join(general_lines), inline=False
        )
        embed.add_field(
            name=strings.CONFIG_SHOW_ZONES_FIELD,
            value="\n".join(zone_lines) if zone_lines else strings.CONFIG_SHOW_NO_ZONES,
            inline=False,
        )
        await send_ephemeral(interaction, embed=embed)


async def setup(bot: "EliteBot") -> None:
    bot.tree.add_command(AdminConfigGroup(bot))
