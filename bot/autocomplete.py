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
