"""Discord UI for the scouting message's per-sub-zone buttons: "Scouting
<name>", "Elite Found" and (once the spawn time arrives) "Elite killed".

There is no separate "spawn has arrived" message anymore: when spawn_at is
reached, the existing scouting message(s) are silently edited in place to add
an "Elite killed" button on every sub-zone row (capturing which sub-zone the
kill happened in), while "Scouting"/"Elite Found" stay active — the boss may
not actually be found/killed exactly on schedule. Clicking "Elite Found"
disables Scouting + Elite Found for the whole zone (across every message —
finding isn't the same as killing, so "Elite killed" stays clickable) and
posts a new pinged announcement. Clicking "Elite killed" disables everything
for good and records the kill (optionally with its sub-zone).

Discord caps a message at 5 action rows, so with one sub-zone per row a zone
can show at most 5 sub-zones per message; zones with more get their buttons
spread across several messages. Only the first ("primary") message carries
the embed. `zone["scouting_messages"]` tracks every message sent for the
current cycle (channel/message id + which sub-zone keys it holds), which is
what lets "Elite Found"/"Elite killed" reach and update every one of them,
not just the one that was clicked. Every per-chunk view is persistent
(`timeout=None`) and re-registered at startup via `bot.add_view(...)` so
clicks keep working on old alert messages after a restart.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord

from bot import domain, strings
from bot.constants import MAPS_DIR
from bot.models import ScoutingMessageRef, ZoneState

if TYPE_CHECKING:
    from bot.main import EliteBot
    from bot.storage import Storage

logger = logging.getLogger(__name__)

_SCOUT_CUSTOM_ID_PREFIX = "elite:scout:"
_FOUND_CUSTOM_ID_PREFIX = "elite:found:"
_KILL_CUSTOM_ID_PREFIX = "elite:kill:"
NO_SUBZONE_KEY = "_none_"  # sentinel used for the kill button on zero-sub-zone zones
MAX_ROWS_PER_MESSAGE = 5  # one sub-zone per row; Discord allows at most 5 action rows


def scout_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_SCOUT_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def found_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_FOUND_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def kill_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_KILL_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def chunk_subzone_keys(zone: ZoneState, chunk_size: int = MAX_ROWS_PER_MESSAGE) -> list[list[str]]:
    keys = list(zone["subzones"].keys())
    return [keys[i : i + chunk_size] for i in range(0, len(keys), chunk_size)]


def build_scouting_embed(
    storage: "Storage", zone_key: str, *, spawn_due: bool = False
) -> discord.Embed:
    zone = storage.data["zones"][zone_key]
    config = storage.data["config"]

    title = (
        strings.scouting_title_spawn_due(zone["display_name"])
        if spawn_due
        else strings.scouting_title(zone["display_name"])
    )
    color = discord.Color.orange() if spawn_due else discord.Color.blue()
    embed = discord.Embed(title=title, color=color)

    spawn_at = zone["spawn_at"]
    if spawn_at is not None:
        embed.description = (
            strings.scouting_spawn_due_description(int(spawn_at))
            if spawn_due
            else strings.pre_alert_description(int(spawn_at), config["alert_offset_minutes"])
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


def build_elite_found_embed(
    storage: "Storage", zone_key: str, subzone_key: str
) -> tuple[discord.Embed, discord.File | None]:
    zone = storage.data["zones"][zone_key]
    subzone_display_name = zone["subzones"][subzone_key]["display_name"]

    embed = discord.Embed(
        title=strings.elite_found_title(subzone_display_name),
        description=strings.elite_found_description(zone["display_name"]),
        color=discord.Color.green(),
    )

    map_path = MAPS_DIR / f"{zone_key}__{subzone_key}.png"
    file = discord.File(map_path, filename=f"{subzone_key}.png") if map_path.exists() else None
    if file is not None:
        embed.set_image(url=f"attachment://{subzone_key}.png")

    return embed, file


class ScoutingView(discord.ui.View):
    def __init__(
        self,
        bot: "EliteBot",
        zone_key: str,
        subzone_keys: list[str],
        *,
        show_kill_button: bool = False,
        scout_disabled: bool = False,
        found_disabled: bool = False,
        kill_disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.zone_key = zone_key

        subzones = bot.storage.data["zones"].get(zone_key, {}).get("subzones", {})

        if not subzone_keys:
            if show_kill_button:
                self._add_kill_button(zone_key, NO_SUBZONE_KEY, 0, kill_disabled)
            return

        for row, subzone_key in enumerate(subzone_keys):
            subzone = subzones.get(subzone_key)
            if subzone is None:
                continue

            scout_button: discord.ui.Button = discord.ui.Button(
                label=strings.scout_button_label(subzone["display_name"]),
                style=discord.ButtonStyle.primary,
                custom_id=scout_custom_id_for(zone_key, subzone_key),
                row=row,
                disabled=scout_disabled,
            )
            scout_button.callback = self._make_scout_callback(subzone_key)
            self.add_item(scout_button)

            found_button: discord.ui.Button = discord.ui.Button(
                emoji=strings.FOUND_BUTTON_EMOJI,
                style=discord.ButtonStyle.success,
                custom_id=found_custom_id_for(zone_key, subzone_key),
                row=row,
                disabled=found_disabled,
            )
            found_button.callback = self._make_found_callback(subzone_key)
            self.add_item(found_button)

            if show_kill_button:
                self._add_kill_button(zone_key, subzone_key, row, kill_disabled)

    def _add_kill_button(self, zone_key: str, subzone_key: str, row: int, disabled: bool) -> None:
        kill_button: discord.ui.Button = discord.ui.Button(
            emoji=strings.KILL_BUTTON_EMOJI,
            style=discord.ButtonStyle.danger,
            custom_id=kill_custom_id_for(zone_key, subzone_key),
            row=row,
            disabled=disabled,
        )
        kill_button.callback = self._make_kill_callback(subzone_key)
        self.add_item(kill_button)

    def _make_scout_callback(self, subzone_key: str):
        async def _callback(interaction: discord.Interaction) -> None:
            await self._on_scout_click(interaction, subzone_key)

        return _callback

    def _make_found_callback(self, subzone_key: str):
        async def _callback(interaction: discord.Interaction) -> None:
            await self._on_found_click(interaction, subzone_key)

        return _callback

    def _make_kill_callback(self, subzone_key: str):
        async def _callback(interaction: discord.Interaction) -> None:
            await self._on_kill_click(interaction, subzone_key)

        return _callback

    async def _on_scout_click(self, interaction: discord.Interaction, subzone_key: str) -> None:
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
            updated_embed = build_scouting_embed(
                storage, self.zone_key, spawn_due=zone["start_alert_sent"]
            )
            refs = zone["scouting_messages"]
            primary_ref = refs[0] if refs else None

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
                await self._edit_message(primary_ref, embed=updated_embed)

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

    async def _on_found_click(self, interaction: discord.Interaction, subzone_key: str) -> None:
        storage = self.bot.storage
        async with storage.lock:
            zone = storage.data["zones"].get(self.zone_key)
            if zone is None or subzone_key not in zone["subzones"]:
                await interaction.response.send_message(strings.ZONE_NOT_FOUND, ephemeral=True)
                return

            zone_display_name = zone["display_name"]
            subzone_display_name = zone["subzones"][subzone_key]["display_name"]
            spawn_due = zone["start_alert_sent"]
            refs = zone["scouting_messages"]
            domain.mark_found(storage.data, self.zone_key)
            await storage.save()

            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to acknowledge elite-found click for %s: %s", self.zone_key, exc
                )

            announce_channel: discord.abc.Messageable | None = None
            for index, ref in enumerate(refs):
                try:
                    channel = self.bot.get_channel(ref["channel_id"])
                    if channel is None:
                        channel = await self.bot.fetch_channel(ref["channel_id"])
                    message = await channel.fetch_message(ref["message_id"])
                    # Finding isn't killing: leave the kill button enabled so
                    # whoever actually gets the kill can still report it.
                    disabled_view = ScoutingView(
                        self.bot,
                        self.zone_key,
                        ref["subzone_keys"],
                        show_kill_button=True,
                        scout_disabled=True,
                        found_disabled=True,
                        kill_disabled=False,
                    )
                    if index == 0:
                        announce_channel = channel
                        done_embed = build_scouting_embed(
                            storage, self.zone_key, spawn_due=spawn_due
                        )
                        done_embed.title = strings.scouting_done_title(zone_display_name)
                        done_embed.add_field(
                            name="​",
                            value=strings.scouting_found_note(subzone_display_name),
                            inline=False,
                        )
                        await message.edit(embed=done_embed, view=disabled_view)
                    else:
                        await message.edit(view=disabled_view)
                except discord.HTTPException as exc:
                    logger.warning(
                        "Failed to disable scouting buttons for %s: %s", self.zone_key, exc
                    )

            if announce_channel is None and refs:
                try:
                    announce_channel = self.bot.get_channel(refs[0]["channel_id"])
                    if announce_channel is None:
                        announce_channel = await self.bot.fetch_channel(refs[0]["channel_id"])
                except discord.HTTPException:
                    announce_channel = None

            if announce_channel is not None:
                role_id = storage.data["config"]["alert_role_id"]
                role_mention = f"<@&{role_id}>" if role_id else None
                found_embed, found_file = build_elite_found_embed(
                    storage, self.zone_key, subzone_key
                )
                try:
                    send_kwargs: dict = {"content": role_mention, "embed": found_embed}
                    if found_file is not None:
                        send_kwargs["file"] = found_file
                    await announce_channel.send(**send_kwargs)
                except discord.HTTPException as exc:
                    logger.warning(
                        "Failed to send elite-found announcement for %s: %s", self.zone_key, exc
                    )

        confirmation = strings.found_confirmed(subzone_display_name)
        if interaction.response.is_done():
            await interaction.followup.send(confirmation, ephemeral=True)
        else:
            await interaction.response.send_message(confirmation, ephemeral=True)

    async def _on_kill_click(self, interaction: discord.Interaction, subzone_key: str) -> None:
        storage = self.bot.storage
        async with storage.lock:
            zone = storage.data["zones"].get(self.zone_key)
            has_subzone = subzone_key != NO_SUBZONE_KEY
            if zone is None or (has_subzone and subzone_key not in zone["subzones"]):
                await interaction.response.send_message(strings.ZONE_NOT_FOUND, ephemeral=True)
                return

            subzone_display_name = (
                zone["subzones"][subzone_key]["display_name"] if has_subzone else None
            )
            refs = zone["scouting_messages"]

            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to acknowledge elite-killed click for %s: %s", self.zone_key, exc
                )

            zone_state = domain.record_kill(
                storage.data,
                self.zone_key,
                time.time(),
                interaction.user.id,
                str(interaction.user),
                subzone_display_name,
            )
            await storage.save()

            zone_display_name = zone_state["display_name"]

            for index, ref in enumerate(refs):
                try:
                    channel = self.bot.get_channel(ref["channel_id"])
                    if channel is None:
                        channel = await self.bot.fetch_channel(ref["channel_id"])
                    message = await channel.fetch_message(ref["message_id"])
                    disabled_view = ScoutingView(
                        self.bot,
                        self.zone_key,
                        ref["subzone_keys"],
                        show_kill_button=True,
                        scout_disabled=True,
                        found_disabled=True,
                        kill_disabled=True,
                    )
                    if index == 0:
                        done_embed = build_scouting_embed(storage, self.zone_key)
                        done_embed.title = strings.scouting_done_title(zone_display_name)
                        done_embed.add_field(
                            name="​",
                            value=strings.scouting_kill_note(subzone_display_name),
                            inline=False,
                        )
                        await message.edit(embed=done_embed, view=disabled_view)
                    else:
                        await message.edit(view=disabled_view)
                except discord.HTTPException as exc:
                    logger.warning(
                        "Failed to disable scouting buttons for %s: %s", self.zone_key, exc
                    )

        confirmation = strings.killed_confirmation(zone_display_name, int(zone_state["spawn_at"]))
        if interaction.response.is_done():
            await interaction.followup.send(confirmation, ephemeral=True)
        else:
            await interaction.response.send_message(confirmation, ephemeral=True)

    async def _edit_message(self, ref: ScoutingMessageRef, **fields) -> None:
        try:
            channel = self.bot.get_channel(ref["channel_id"])
            if channel is None:
                channel = await self.bot.fetch_channel(ref["channel_id"])
            message = await channel.fetch_message(ref["message_id"])
            await message.edit(**fields)
        except discord.HTTPException as exc:
            logger.warning("Failed to update scouting message for %s: %s", self.zone_key, exc)
