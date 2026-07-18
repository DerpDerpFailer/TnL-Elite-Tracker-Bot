"""Discord UI for the pre-alert's per-sub-zone "Scouting" buttons.

Clicking a button toggles that member in/out of the sub-zone's scout list
(persisted in elite.json) and rebuilds the shared embed so the whole channel
sees who's checking which spot. Like KillButtonView, this view is persistent
(`timeout=None`) and re-registered per zone at startup via `bot.add_view(...)`
so clicks keep working on old alert messages after a restart.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from bot import domain, strings
from bot.constants import MAPS_DIR
from bot.storage import Storage

if TYPE_CHECKING:
    from bot.main import EliteBot

logger = logging.getLogger(__name__)

_CUSTOM_ID_PREFIX = "elite:scout:"


def custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


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
    def __init__(self, bot: "EliteBot", zone_key: str) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.zone_key = zone_key

        zone = bot.storage.data["zones"].get(zone_key, {})
        for subzone_key, subzone in zone.get("subzones", {}).items():
            button: discord.ui.Button = discord.ui.Button(
                label=strings.scout_button_label(subzone["display_name"]),
                style=discord.ButtonStyle.primary,
                custom_id=custom_id_for(zone_key, subzone_key),
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

        try:
            await interaction.response.edit_message(embed=updated_embed, view=self)
        except discord.HTTPException as exc:
            logger.warning("Failed to update scouting embed for %s: %s", self.zone_key, exc)

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
