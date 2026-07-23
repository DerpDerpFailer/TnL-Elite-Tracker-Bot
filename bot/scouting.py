"""Discord UI for the scouting message's per-sub-zone buttons: "🔍 <name>",
"📍" (Elite Found) and (once the spawn time arrives) "💀" (Elite killed) —
plus the two buttons on the Elite Found announcement itself: "💀" (kill,
duplicated there so it's not necessary to scroll back to the scouting
message) and "🔄" (undo the found report).

There is no separate "spawn has arrived" message anymore: when spawn_at is
reached, the existing scouting message(s) are silently edited in place to add
a 💀 button on every sub-zone row (capturing which sub-zone the kill happened
in), while 🔍/📍 stay active — the boss may not actually be found/killed
exactly on schedule. Clicking 📍 disables 🔍/📍 for the whole zone (across
every message — finding isn't the same as killing, so 💀 stays clickable)
and posts a new pinged announcement with its own 💀/🔄 buttons. Clicking 💀
(from either place) closes out *this zone's* cycle only — every scouting
message and the Elite Found announcement (if any) for that zone are
*deleted* (not just disabled), and a new "Boss killed" summary embed (zone,
sub-zone, kill time, reporter) is posted in their place. Clicking 🔄 on the
announcement instead reverts the found report without killing anything: it
re-enables 🔍/📍 on the scouting message(s) and deletes the announcement.

Discord caps a message at 5 action rows, so with one sub-zone per row a zone
can show at most 5 sub-zones per message; zones with more get their buttons
spread across several messages. Only the first ("primary") message *per
installed guild* carries the embed (see group_refs_by_guild). Both
`zone["scouting_messages"]` and `zone["found_announcement_messages"]` are
guild-tagged lists tracking every message sent for the current cycle, across
every installed guild (channel/message id + which sub-zone keys each
scouting message holds), which is what lets 📍/💀 reach and update/delete
every one of them, in every guild, not just the one that was clicked — a
report on one server is mirrored to every other installed server. Every view
here is persistent (`timeout=None`) and re-registered at startup via
`bot.add_view(...)` so clicks keep working on old alert messages after a
restart.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord

from bot import domain, strings
from bot.constants import MAPS_DIR
from bot.interactions import send_ephemeral
from bot.models import ScoutingMessageRef, ZoneState

if TYPE_CHECKING:
    from bot.main import EliteBot
    from bot.storage import Storage

logger = logging.getLogger(__name__)

_SCOUT_CUSTOM_ID_PREFIX = "elite:scout:"
_FOUND_CUSTOM_ID_PREFIX = "elite:found:"
_KILL_CUSTOM_ID_PREFIX = "elite:kill:"
_FOUND_KILL_CUSTOM_ID_PREFIX = "elite:foundkill:"
_FOUND_UNDO_CUSTOM_ID_PREFIX = "elite:foundundo:"
NO_SUBZONE_KEY = "_none_"  # sentinel used for the kill button on zero-sub-zone zones
MAX_ROWS_PER_MESSAGE = 5  # one sub-zone per row; Discord allows at most 5 action rows


def scout_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_SCOUT_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def found_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_FOUND_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def kill_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_KILL_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def found_kill_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_FOUND_KILL_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def found_undo_custom_id_for(zone_key: str, subzone_key: str) -> str:
    return f"{_FOUND_UNDO_CUSTOM_ID_PREFIX}{zone_key}:{subzone_key}"


def chunk_subzone_keys(zone: ZoneState, chunk_size: int = MAX_ROWS_PER_MESSAGE) -> list[list[str]]:
    keys = list(zone["subzones"].keys())
    return [keys[i : i + chunk_size] for i in range(0, len(keys), chunk_size)]


def group_refs_by_guild(refs: list[dict]) -> dict[int, list[dict]]:
    """Groups a flat list of guild-tagged message refs (ScoutingMessageRef or
    MessageRef) by guild_id, preserving order — each installed guild gets its
    own copy of a zone's scouting/found messages, and within a guild's group
    the first ref is that guild's "primary" message (the one carrying the
    embed; any others are chunk-continuation messages, view-only)."""
    groups: dict[int, list[dict]] = {}
    for ref in refs:
        groups.setdefault(ref["guild_id"], []).append(ref)
    return groups


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


def build_boss_killed_embed(
    zone_display_name: str,
    subzone_display_name: str | None,
    kill_ts: float,
    reported_by: str,
    spawn_at: float,
) -> discord.Embed:
    embed = discord.Embed(title=strings.BOSS_KILLED_TITLE, color=discord.Color.dark_red())
    embed.add_field(name=strings.BOSS_KILLED_ZONE_FIELD, value=zone_display_name, inline=True)
    embed.add_field(
        name=strings.BOSS_KILLED_SUBZONE_FIELD,
        value=subzone_display_name or strings.BOSS_KILLED_UNKNOWN_SUBZONE,
        inline=True,
    )
    embed.add_field(
        name=strings.BOSS_KILLED_TIME_FIELD, value=f"<t:{int(kill_ts)}:F>", inline=False
    )
    embed.add_field(
        name=strings.BOSS_KILLED_NEXT_SPAWN_FIELD,
        value=strings.boss_killed_next_spawn_value(int(spawn_at)),
        inline=False,
    )
    embed.add_field(
        name=strings.BOSS_KILLED_REPORTED_BY_FIELD, value=reported_by, inline=False
    )
    return embed


async def _resolve_channel(bot: "EliteBot", channel_id: int) -> discord.abc.Messageable | None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            return None
    return channel


async def _delete_tracked_message(bot: "EliteBot", zone_key: str, ref: dict, what: str) -> None:
    channel = await _resolve_channel(bot, ref["channel_id"])
    if channel is None:
        logger.warning(
            "Channel %s could not be resolved, skipping %s deletion", ref["channel_id"], what
        )
        return
    try:
        message = await channel.fetch_message(ref["message_id"])
        await message.delete()
    except discord.HTTPException as exc:
        logger.warning("Failed to delete %s for %s: %s", what, zone_key, exc)


async def record_kill_and_close_scouting(
    bot: "EliteBot",
    zone_key: str,
    subzone_key: str,
    user_id: int,
    user_name: str,
    *,
    timestamp: float | None = None,
    reported_by_display: str | None = None,
) -> ZoneState | None:
    """Records the kill (optionally for a specific sub-zone), then closes
    out *this zone's* cycle only: every scouting message and the Elite Found
    announcement (if any) tracked for it are deleted, replaced by a new
    "Boss killed" summary posted in the same channel. Shared by the scouting
    message's per-row kill button and the Elite Found announcement's kill
    button. Returns None if the zone/sub-zone no longer exists (e.g. removed
    by an admin mid-cycle).

    Acquires the zone's lock itself — callers that already hold it (e.g.
    bot/fallback.py's sync_zone_from_fallback, which needs the lock across
    its own "is this newer" check) must call
    `record_kill_and_close_scouting_locked` directly instead, since
    asyncio.Lock isn't reentrant."""
    async with bot.storage.zone_lock(zone_key):
        return await record_kill_and_close_scouting_locked(
            bot,
            zone_key,
            subzone_key,
            user_id,
            user_name,
            timestamp=timestamp,
            reported_by_display=reported_by_display,
        )


async def record_kill_and_close_scouting_locked(
    bot: "EliteBot",
    zone_key: str,
    subzone_key: str,
    user_id: int,
    user_name: str,
    *,
    timestamp: float | None = None,
    reported_by_display: str | None = None,
) -> ZoneState | None:
    """Same as `record_kill_and_close_scouting`, but assumes the caller
    already holds `storage.zone_lock(zone_key)`.

    `timestamp` defaults to now (a live button click); pass the actual kill
    time for a kill recorded after the fact (e.g. the fallback sync).
    `reported_by_display` defaults to a `<@user_id>` mention (a real Discord
    reporter); pass a plain string when there isn't one."""
    storage = bot.storage
    zone = storage.data["zones"].get(zone_key)
    has_subzone = subzone_key != NO_SUBZONE_KEY
    if zone is None or (has_subzone and subzone_key not in zone["subzones"]):
        return None

    subzone_display_name = zone["subzones"][subzone_key]["display_name"] if has_subzone else None
    scouting_refs = list(zone["scouting_messages"])
    found_refs = list(zone["found_announcement_messages"])

    kill_ts = timestamp if timestamp is not None else time.time()
    zone_state = domain.record_kill(
        storage.data, zone_key, kill_ts, user_id, user_name, subzone_display_name
    )
    await storage.save()

    for ref in scouting_refs:
        await _delete_tracked_message(bot, zone_key, ref, "scouting message")
    for ref in found_refs:
        await _delete_tracked_message(bot, zone_key, ref, "elite-found announcement")

    # One "Boss killed" summary per guild that had a live scouting/found
    # message — each guild's own channel, same as the alerts it's replacing.
    # A guild's scouting channel takes priority over its found-announcement
    # channel (matches which one used to win when there was only one guild).
    target_channels: dict[int, int] = {}
    for ref in scouting_refs:
        target_channels.setdefault(ref["guild_id"], ref["channel_id"])
    for ref in found_refs:
        target_channels.setdefault(ref["guild_id"], ref["channel_id"])

    if target_channels:
        reported_by = reported_by_display if reported_by_display is not None else f"<@{user_id}>"
        killed_embed = build_boss_killed_embed(
            zone_state["display_name"],
            subzone_display_name,
            zone_state["last_kill_at"],
            reported_by,
            zone_state["spawn_at"],
        )
        for channel_id in target_channels.values():
            target_channel = await _resolve_channel(bot, channel_id)
            if target_channel is None:
                continue
            try:
                await target_channel.send(embed=killed_embed)
            except discord.HTTPException as exc:
                logger.warning("Failed to send boss-killed summary for %s: %s", zone_key, exc)

    return zone_state


async def mark_found_and_announce(
    bot: "EliteBot", zone_key: str, subzone_key: str
) -> ZoneState | None:
    """Marks the zone found at this sub-zone, disables scout/found buttons on
    every tracked scouting message (kill stays enabled — finding isn't
    killing), and posts the pinged Elite Found announcement. Returns the
    zone state, or None if the zone/sub-zone no longer exists.

    Acquires the zone's lock itself — callers that already hold it must call
    `mark_found_and_announce_locked` directly instead (asyncio.Lock isn't
    reentrant), same reasoning as record_kill_and_close_scouting above."""
    async with bot.storage.zone_lock(zone_key):
        return await mark_found_and_announce_locked(bot, zone_key, subzone_key)


async def mark_found_and_announce_locked(
    bot: "EliteBot", zone_key: str, subzone_key: str
) -> ZoneState | None:
    """Same as `mark_found_and_announce`, but assumes the caller already
    holds `storage.zone_lock(zone_key)` — e.g. bot/fallback.py's found-watch
    loop, which checks mmopartybuilder.eu for a "found" report and needs the
    lock held across that check."""
    storage = bot.storage
    zone = storage.data["zones"].get(zone_key)
    if zone is None or subzone_key not in zone["subzones"]:
        return None

    zone_display_name = zone["display_name"]
    subzone_display_name = zone["subzones"][subzone_key]["display_name"]
    spawn_due = zone["spawn_due_marked"]
    refs_by_guild = group_refs_by_guild(zone["scouting_messages"])
    domain.mark_found(storage.data, zone_key)
    await storage.save()

    done_embed = build_scouting_embed(storage, zone_key, spawn_due=spawn_due)
    done_embed.title = strings.scouting_done_title(zone_display_name)
    done_embed.add_field(
        name="​", value=strings.scouting_found_note(subzone_display_name), inline=False
    )

    # Every installed guild gets its own copy of the scouting messages
    # disabled and its own Elite Found announcement, pinged with its own
    # alert role.
    new_found_refs: list[dict] = []
    for guild_id, refs in refs_by_guild.items():
        announce_channel: discord.abc.Messageable | None = None
        for index, ref in enumerate(refs):
            try:
                channel = bot.get_channel(ref["channel_id"])
                if channel is None:
                    channel = await bot.fetch_channel(ref["channel_id"])
                message = await channel.fetch_message(ref["message_id"])
                # Finding isn't killing: leave the kill button enabled so
                # whoever actually gets the kill can still report it.
                disabled_view = ScoutingView(
                    bot,
                    zone_key,
                    ref["subzone_keys"],
                    show_kill_button=True,
                    scout_disabled=True,
                    found_disabled=True,
                )
                if index == 0:
                    announce_channel = channel
                    await message.edit(embed=done_embed, view=disabled_view)
                else:
                    await message.edit(view=disabled_view)
            except discord.HTTPException as exc:
                logger.warning("Failed to disable scouting buttons for %s: %s", zone_key, exc)

        if announce_channel is None and refs:
            try:
                announce_channel = bot.get_channel(refs[0]["channel_id"])
                if announce_channel is None:
                    announce_channel = await bot.fetch_channel(refs[0]["channel_id"])
            except discord.HTTPException:
                announce_channel = None

        if announce_channel is None:
            continue

        guild_config = storage.data["guilds"].get(str(guild_id))
        role_id = guild_config["alert_role_id"] if guild_config else None
        role_mention = f"<@&{role_id}>" if role_id else None
        found_embed, found_file = build_elite_found_embed(storage, zone_key, subzone_key)
        found_view = FoundAnnouncementView(bot, zone_key, subzone_key)
        try:
            send_kwargs: dict = {
                "content": role_mention,
                "embed": found_embed,
                "view": found_view,
            }
            if found_file is not None:
                send_kwargs["file"] = found_file
            announcement_message = await announce_channel.send(**send_kwargs)
        except discord.HTTPException as exc:
            logger.warning("Failed to send elite-found announcement for %s: %s", zone_key, exc)
        else:
            new_found_refs.append(
                {
                    "guild_id": guild_id,
                    "channel_id": announce_channel.id,
                    "message_id": announcement_message.id,
                }
            )

    if new_found_refs:
        zone["found_announcement_messages"] = new_found_refs
        await storage.save()

    return zone


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
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.zone_key = zone_key

        subzones = bot.storage.data["zones"].get(zone_key, {}).get("subzones", {})

        if not subzone_keys:
            if show_kill_button:
                self._add_kill_button(zone_key, NO_SUBZONE_KEY, 0)
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
                self._add_kill_button(zone_key, subzone_key, row)

    def _add_kill_button(self, zone_key: str, subzone_key: str, row: int) -> None:
        kill_button: discord.ui.Button = discord.ui.Button(
            emoji=strings.KILL_BUTTON_EMOJI,
            style=discord.ButtonStyle.danger,
            custom_id=kill_custom_id_for(zone_key, subzone_key),
            row=row,
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
        async with storage.zone_lock(self.zone_key):
            zone = storage.data["zones"].get(self.zone_key)
            if zone is None or subzone_key not in zone["subzones"]:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            now_scouting = domain.toggle_scout(
                storage.data, self.zone_key, subzone_key, interaction.user.id
            )
            await storage.save()

            zone_display_name = zone["display_name"]
            subzone_display_name = zone["subzones"][subzone_key]["display_name"]
            updated_embed = build_scouting_embed(
                storage, self.zone_key, spawn_due=zone["spawn_due_marked"]
            )
            # One primary (embed-carrying) ref per installed guild — a scout
            # report is shared state, so every guild's own copy needs the
            # refreshed embed, not just the one that was clicked.
            primary_refs = [
                refs[0] for refs in group_refs_by_guild(zone["scouting_messages"]).values()
            ]

        clicked_primary_ref = next(
            (
                ref
                for ref in primary_refs
                if interaction.message is not None and interaction.message.id == ref["message_id"]
            ),
            None,
        )

        if clicked_primary_ref is not None:
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

        for ref in primary_refs:
            if ref is clicked_primary_ref:
                continue
            await self._edit_message(ref, embed=updated_embed)

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

        ephemeral_kwargs: dict = {}
        if file is not None:
            ephemeral_kwargs["file"] = file
        await send_ephemeral(interaction, confirmation, **ephemeral_kwargs)

    async def _on_found_click(self, interaction: discord.Interaction, subzone_key: str) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException as exc:
            logger.warning(
                "Failed to acknowledge elite-found click for %s: %s", self.zone_key, exc
            )

        zone_state = await mark_found_and_announce(self.bot, self.zone_key, subzone_key)
        if zone_state is None:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return

        subzone_display_name = zone_state["subzones"][subzone_key]["display_name"]
        confirmation = strings.found_confirmed(subzone_display_name)
        await send_ephemeral(interaction, confirmation)

    async def _on_kill_click(self, interaction: discord.Interaction, subzone_key: str) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException as exc:
            logger.warning(
                "Failed to acknowledge elite-killed click for %s: %s", self.zone_key, exc
            )

        zone_state = await record_kill_and_close_scouting(
            self.bot, self.zone_key, subzone_key, interaction.user.id, str(interaction.user)
        )
        if zone_state is None:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return

        confirmation = strings.killed_confirmation(zone_state["display_name"], int(zone_state["spawn_at"]))
        await send_ephemeral(interaction, confirmation)

    async def _edit_message(self, ref: ScoutingMessageRef, **fields) -> None:
        try:
            channel = self.bot.get_channel(ref["channel_id"])
            if channel is None:
                channel = await self.bot.fetch_channel(ref["channel_id"])
            message = await channel.fetch_message(ref["message_id"])
            await message.edit(**fields)
        except discord.HTTPException as exc:
            logger.warning("Failed to update scouting message for %s: %s", self.zone_key, exc)


class FoundAnnouncementView(discord.ui.View):
    """The 💀/🔄 buttons attached to the Elite Found announcement message."""

    def __init__(self, bot: "EliteBot", zone_key: str, subzone_key: str) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.zone_key = zone_key
        self.subzone_key = subzone_key

        kill_button: discord.ui.Button = discord.ui.Button(
            emoji=strings.KILL_BUTTON_EMOJI,
            style=discord.ButtonStyle.danger,
            custom_id=found_kill_custom_id_for(zone_key, subzone_key),
            row=0,
        )
        kill_button.callback = self._on_kill_click
        self.add_item(kill_button)

        undo_button: discord.ui.Button = discord.ui.Button(
            emoji=strings.UNDO_BUTTON_EMOJI,
            style=discord.ButtonStyle.secondary,
            custom_id=found_undo_custom_id_for(zone_key, subzone_key),
            row=0,
        )
        undo_button.callback = self._on_undo_click
        self.add_item(undo_button)

    async def _on_kill_click(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException as exc:
            logger.warning(
                "Failed to acknowledge elite-killed click for %s: %s", self.zone_key, exc
            )

        # record_kill_and_close_scouting deletes this very announcement
        # message (tracked in found_announcement_messages) as part of closing
        # out the zone's cycle, so there's nothing left here to disable/edit.
        zone_state = await record_kill_and_close_scouting(
            self.bot, self.zone_key, self.subzone_key, interaction.user.id, str(interaction.user)
        )
        if zone_state is None:
            await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
            return

        confirmation = strings.killed_confirmation(zone_state["display_name"], int(zone_state["spawn_at"]))
        await send_ephemeral(interaction, confirmation)

    async def _on_undo_click(self, interaction: discord.Interaction) -> None:
        storage = self.bot.storage
        async with storage.zone_lock(self.zone_key):
            zone = storage.data["zones"].get(self.zone_key)
            if zone is None:
                await send_ephemeral(interaction, strings.ZONE_NOT_FOUND)
                return

            zone_display_name = zone["display_name"]
            spawn_due = zone["spawn_due_marked"]
            refs_by_guild = group_refs_by_guild(zone["scouting_messages"])
            found_refs = list(zone["found_announcement_messages"])
            zone["found_this_cycle"] = False
            zone["found_announcement_messages"] = []
            await storage.save()

        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException as exc:
            logger.warning(
                "Failed to acknowledge elite-found undo click for %s: %s", self.zone_key, exc
            )

        # "Found" is shared state: undoing it re-enables scouting and drops
        # the announcement in every installed guild, not just the one whose
        # button was clicked.
        for refs in refs_by_guild.values():
            for index, ref in enumerate(refs):
                try:
                    channel = self.bot.get_channel(ref["channel_id"])
                    if channel is None:
                        channel = await self.bot.fetch_channel(ref["channel_id"])
                    message = await channel.fetch_message(ref["message_id"])
                    view = ScoutingView(
                        self.bot, self.zone_key, ref["subzone_keys"], show_kill_button=spawn_due
                    )
                    if index == 0:
                        embed = build_scouting_embed(storage, self.zone_key, spawn_due=spawn_due)
                        await message.edit(embed=embed, view=view)
                    else:
                        await message.edit(view=view)
                except discord.HTTPException as exc:
                    logger.warning(
                        "Failed to re-enable scouting buttons for %s: %s", self.zone_key, exc
                    )

        for ref in found_refs:
            await _delete_tracked_message(self.bot, self.zone_key, ref, "elite-found announcement")

        await send_ephemeral(interaction, strings.found_undone(zone_display_name))
