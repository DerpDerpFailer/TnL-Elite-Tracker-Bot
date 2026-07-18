"""Discord UI: the persistent "Elite killed" button attached to spawn-open
alerts, letting anyone confirm the kill (and restart the zone's timer)
straight from the alert message instead of typing /elite-killed.

The button is persistent (`timeout=None`) so it keeps working across bot
restarts: `EliteBot.setup_hook` re-registers one `KillButtonView` per known
zone via `bot.add_view(...)`, which is what lets Discord route a click on an
old alert message back to this callback even though the original view
instance was lost when the process restarted.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord

from bot import domain, strings

if TYPE_CHECKING:
    from bot.main import EliteBot

logger = logging.getLogger(__name__)

_CUSTOM_ID_PREFIX = "elite:kill:"


def custom_id_for(zone_key: str) -> str:
    return f"{_CUSTOM_ID_PREFIX}{zone_key}"


class KillButtonView(discord.ui.View):
    def __init__(
        self,
        bot: "EliteBot",
        zone_key: str,
        *,
        disabled: bool = False,
        label_override: str | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.zone_key = zone_key

        button: discord.ui.Button = discord.ui.Button(
            label=label_override or strings.KILL_BUTTON_LABEL,
            style=discord.ButtonStyle.success if disabled else discord.ButtonStyle.danger,
            custom_id=custom_id_for(zone_key),
            disabled=disabled,
        )
        button.callback = self._on_click
        self.add_item(button)

    async def _on_click(self, interaction: discord.Interaction) -> None:
        storage = self.bot.storage
        async with storage.lock:
            if self.zone_key not in storage.data["zones"]:
                await interaction.response.send_message(strings.ZONE_NOT_FOUND, ephemeral=True)
                return

            zone_state = domain.record_kill(
                storage.data,
                self.zone_key,
                time.time(),
                interaction.user.id,
                str(interaction.user),
            )
            await storage.save()

        display_name = zone_state["display_name"]
        confirmed_view = KillButtonView(
            self.bot,
            self.zone_key,
            disabled=True,
            label_override=strings.kill_button_confirmed_label(interaction.user.display_name),
        )
        try:
            await interaction.response.edit_message(view=confirmed_view)
        except discord.HTTPException as exc:
            logger.warning("Failed to disable kill button for %s: %s", self.zone_key, exc)

        confirmation = strings.killed_confirmation(display_name, int(zone_state["spawn_at"]))
        if interaction.response.is_done():
            await interaction.followup.send(confirmation, ephemeral=True)
        else:
            await interaction.response.send_message(confirmation, ephemeral=True)

        await self.bot.perpetual.force_update(self.bot, time.time())
