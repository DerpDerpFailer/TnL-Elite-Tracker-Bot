"""Discord UI for the pre-alert's per-sub-zone "Scouting" buttons.

Clicking a button toggles that member in/out of the sub-zone's scout list
(persisted in elite.json) and rebuilds the shared embed so the whole channel
sees who's checking which spot. Like KillButtonView, each per-chunk view is
persistent (`timeout=None`) and re-registered per zone/chunk at startup via
`bot.add_view(...)` so clicks keep working on old alert messages after a
restart.

Discord caps a message at 5 action rows, so with one button per row (the
requested layout) a zone can show at most 5 sub-zone buttons per message.
Zones with more sub-zones get their buttons spread across several messages;
only the first ("primary") message carries the embed, and buttons on the
later ones fetch-and-edit that primary message to reflect a click.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from bot import domain, strings
from bot.constants import MAPS_DIR
from bot.models import ScoutingMessageRef, ZoneState
from bot.storage import Storage

if TYPE_CHECKING:
    from bot.main import EliteBot

logger = logging.getLogger(__name__)

_CUSTOM_ID_PREFIX = "elite:scout:"
MAX_BUTTONS_PER_MESSAGE = 5  # one per row; Discord allows at most 5 action rows


def custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def chunk_subzone_keys(zone: ZoneState, chunk_size: int = MAX_BUTTONS_PER_MESSAGE) -> list[list[str]]:
    keys = list(zone["subzones"].keys())
    return [keys[i : i + chunk_size] for i in range(0, len(keys), chunk_size)]


def build_scouting_embed(storage: Storage, zone_key: str) -> discord.Embed:
    zone = storage.data["zones"][zone_key]
    config = storage.data["config"]

    embed = discord.Embed(title=strings.scouting_title(zone["display_name"]), color=discord.Color.blue())

    spawn_at = zone["spawn_at"]
    if spawn_at is not None:
        embed.description = strings.pre_alert_description(
            int(spawn_at), config["alert_offset_minutes"]
        )

    for subzone in zone["subzones"].values():
        mentions = [f"<@{user_id}>" for user_id in subzone["scouts"]]
        embed.add_field(
            name=subzone["display_name"],
            value=strings.scouting_field_value(mentions),
            inline=True,
        )

    embed.add_field(name="​", value=strings.MAP_REMINDER_NOTE, inline=False)

    if (MAPS_DIR / f"{zone_key}.png").exists():
        embed.set_image(url=f"attachment://{zone_key}.png")

    return embed


class ScoutingView(discord.ui.View):
    def __init__(self, bot: "EliteBot", zone_key: str, subzone_keys: list[str]) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.zone_key = zone_key

        subzones = bot.storage.data["zones"].get(zone_key, {}).get("subzones", {})
        for row, subzone_key in enumerate(subzone_keys):
            subzone = subzones.get(subzone_key)
            if subzone is None:
                continue
            button: discord.ui.Button = discord.ui.Button(
                label=strings.scout_button_label(subzone["display_name"]),
                style=discord.ButtonStyle.primary,
                custom_id=custom_id_for(zone_key, subzone_key),
                row=row,
            )
            button.callback = self._make_callback(subzone_key)
            self.add_item(button)

    def _make_callback(self, subzone_key: str):
        async def _callback(interaction: discord.Interaction) -> None:
            await self._on_click(interaction, subzone_key)

        return _callback

    async def _on_click(self, interaction: discord.Interaction, subzone_key: str) -> None:
        storage = self.bot.storage
        async with storage.lock:
            zone = storage.data["zones"].get(self.zone_key)
            if zone is None or subzone_key not in zone["subzones"]:
                await interaction.response.send_message(strings.ZONE_NOT_FOUND, ephemeral=True)
                return

            now_scouting = domain.toggle_scout(
                storage.data, self.zone_key, subzone_key, interaction.user.id
            )
            await storage.save()

            zone_display_name = zone["display_name"]
            subzone_display_name = zone["subzones"][subzone_key]["display_name"]
            updated_embed = build_scouting_embed(storage, self.zone_key)
            primary_ref = zone["scouting_message"]

        is_primary_message = (
            primary_ref is not None
            and interaction.message is not None
            and interaction.message.id == primary_ref["message_id"]
        )

        if is_primary_message:
            try:
                await interaction.response.edit_message(embed=updated_embed, view=self)
            except discord.HTTPException as exc:
                logger.warning("Failed to update scouting embed for %s: %s", self.zone_key, exc)
        else:
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to acknowledge scouting click for %s: %s", self.zone_key, exc
                )
            if primary_ref is not None:
                await self._update_primary_message(primary_ref, updated_embed)

        confirmation = (
            strings.scout_confirmed(subzone_display_name, zone_display_name)
            if now_scouting
            else strings.scout_cancelled(subzone_display_name)
        )

        map_path = MAPS_DIR / f"{self.zone_key}__{subzone_key}.png"
        file = (
            discord.File(map_path, filename=f"{subzone_key}.png")
            if now_scouting and map_path.exists()
            else None
        )

        kwargs: dict = {"content": confirmation, "ephemeral": True}
        if file is not None:
            kwargs["file"] = file

        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)

    async def _update_primary_message(
        self, primary_ref: ScoutingMessageRef, embed: discord.Embed
    ) -> None:
        try:
            channel = self.bot.get_channel(primary_ref["channel_id"])
            if channel is None:
                channel = await self.bot.fetch_channel(primary_ref["channel_id"])
            message = await channel.fetch_message(primary_ref["message_id"])
            await message.edit(embed=embed)
        except discord.HTTPException as exc:
            logger.warning(
                "Failed to refresh primary scouting message for %s: %s", self.zone_key, exc
            )
