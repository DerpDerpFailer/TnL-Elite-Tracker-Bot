"""Shared autocomplete callbacks used by both member and admin commands."""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from bot.main import EliteBot


async def zone_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    bot: "EliteBot" = interaction.client  # type: ignore[assignment]
    current_lower = current.lower()
    matches = [
        app_commands.Choice(name=zone["display_name"], value=key)
        for key, zone in bot.storage.data["zones"].items()
        if current_lower in zone["display_name"].lower()
    ]
    return matches[:25]


async def subzone_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Filtered by whatever the command's `zone` parameter currently holds —
    empty until the member picks a zone first."""
    bot: "EliteBot" = interaction.client  # type: ignore[assignment]
    zone_key = getattr(interaction.namespace, "zone", None)
    zone = bot.storage.data["zones"].get(zone_key) if zone_key else None
    if zone is None:
        return []

    current_lower = current.lower()
    matches = [
        app_commands.Choice(name=subzone["display_name"], value=subzone_key)
        for subzone_key, subzone in zone["subzones"].items()
        if current_lower in subzone["display_name"].lower()
    ]
    return matches[:25]
