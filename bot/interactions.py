"""Shared helpers for interaction replies.

`send_reply` routes to `interaction.response.send_message` or
`interaction.followup.send` depending on whether the interaction has already
been responded to (e.g. after a `defer()`, or for a later chunk of a
multi-message reply) — commands/components should never call those two
directly. `send_ephemeral` is the common case built on top of it: every
ephemeral confirmation/error is meant to be read once and then get out of
the way, so it's scheduled for deletion a few seconds later using discord.py's
native support for it (`delete_after` on the initial response,
`Message.delete(delay=...)` on a followup — both fire-and-forget background
tasks handled by discord.py itself, not something we need to track).
"""
from __future__ import annotations

import discord

EPHEMERAL_TTL_SECONDS: float = 12.0


async def send_reply(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    ephemeral: bool = False,
    **kwargs,
) -> None:
    kwargs["ephemeral"] = ephemeral
    if interaction.response.is_done():
        message = await interaction.followup.send(content, wait=True, **kwargs)
        if ephemeral and message is not None:
            await message.delete(delay=EPHEMERAL_TTL_SECONDS)
    else:
        delete_after = EPHEMERAL_TTL_SECONDS if ephemeral else None
        await interaction.response.send_message(content, delete_after=delete_after, **kwargs)


async def send_ephemeral(interaction: discord.Interaction, content: str | None = None, **kwargs) -> None:
    await send_reply(interaction, content, ephemeral=True, **kwargs)
