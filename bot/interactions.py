"""Shared helper for ephemeral interaction replies.

Every ephemeral confirmation/error the bot sends is meant to be read once
and then get out of the way — so instead of calling
`interaction.response.send_message(..., ephemeral=True)` /
`interaction.followup.send(..., ephemeral=True)` directly, commands and
components call `send_ephemeral` here, which schedules the reply for
deletion a few seconds later using discord.py's native support for it
(`delete_after` on the initial response, `Message.delete(delay=...)` on a
followup — both fire-and-forget background tasks handled by discord.py
itself, not something we need to track).
"""
from __future__ import annotations

import discord

EPHEMERAL_TTL_SECONDS: float = 12.0


async def send_ephemeral(interaction: discord.Interaction, content: str | None = None, **kwargs) -> None:
    kwargs["ephemeral"] = True
    if interaction.response.is_done():
        message = await interaction.followup.send(content, wait=True, **kwargs)
        if message is not None:
            await message.delete(delay=EPHEMERAL_TTL_SECONDS)
    else:
        await interaction.response.send_message(
            content, delete_after=EPHEMERAL_TTL_SECONDS, **kwargs
        )
