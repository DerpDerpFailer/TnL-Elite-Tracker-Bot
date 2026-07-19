"""Centralized user-facing strings.

Every string a user can see (command replies, embeds, alerts) lives here as a
plain function or constant. Commands and background tasks must never build
user-facing text inline — they call into this module instead. This is what
lets a future i18n layer be dropped in (e.g. swapping these functions for
lookups keyed by the interaction's locale) without touching command logic.
"""
from __future__ import annotations

from bot.models import ZonePhase

# ---------------------------------------------------------------------------
# Perpetual status message
# ---------------------------------------------------------------------------

PHASE_EMOJI: dict[ZonePhase, str] = {
    ZonePhase.ACTIVE: "\U0001f7e2",  # 🟢 spawn time has passed, no kill logged since
    ZonePhase.IMMINENT: "\U0001f7e1",  # 🟡 spawn expected in under 30 minutes
    ZonePhase.WAITING: "⚪",  # ⚪ waiting for cooldown to elapse
    ZonePhase.NO_DATA: "❓",  # ❓ no kill has ever been recorded
}

STATUS_EMBED_TITLE = "Elite Boss Timers"
STATUS_EMBED_DESCRIPTION = "Live respawn windows for every tracked Elite PvP zone."
STATUS_EMBED_FOOTER = "Use /elite-killed to report a kill"


def status_embed_updated_line(updated_ts: int) -> str:
    return f"Last updated <t:{updated_ts}:R>"


def zone_field_name(emoji: str, display_name: str) -> str:
    return f"{emoji} {display_name}"


def _format_duration_words(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return " ".join(parts) if parts else "0 minutes"


def zone_field_value_no_data(cooldown_minutes: int) -> str:
    return (
        "No kill recorded yet\n"
        f"Cooldown: {_format_duration_words(cooldown_minutes)}"
    )


def zone_field_value(
    last_kill_ts: int,
    spawn_at_ts: int,
    cooldown_minutes: int,
    last_kill_subzone: str | None = None,
) -> str:
    subzone_note = f" in **{last_kill_subzone}**" if last_kill_subzone else ""
    return (
        f"Respawning: <t:{spawn_at_ts}:R>\n"
        f"Last killed: <t:{last_kill_ts}:F> (<t:{last_kill_ts}:R>){subzone_note}\n"
        f"Spawn time: <t:{spawn_at_ts}:F>\n"
        f"Cooldown: {_format_duration_words(cooldown_minutes)}"
    )


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

MAP_REMINDER_NOTE = (
    "Reminder: the in-game map icon only appears once you're close to the spawn point, "
    "and the red pillar shows up about 1 minute before the boss actually spawns."
)


def pre_alert_description(spawn_at_ts: int, offset_minutes: int) -> str:
    return (
        f"Spawn expected in about {offset_minutes} minutes: "
        f"<t:{spawn_at_ts}:t> (<t:{spawn_at_ts}:R>)"
    )


def scouting_title(display_name: str) -> str:
    return f"\U0001f526 {display_name} Scouting"


def scouting_title_spawn_due(display_name: str) -> str:
    return f"\U0001f6a8 {display_name} Scouting — Spawn Due"


def scouting_spawn_due_description(spawn_at_ts: int) -> str:
    return f"Spawn time was <t:{spawn_at_ts}:t> (<t:{spawn_at_ts}:R>) — should be up now!"


def scouting_field_value(mentions: list[str]) -> str:
    scouting_line = "Scouting: " + (", ".join(mentions) if mentions else "Nobody yet")
    return f"{scouting_line}\nNumber of Scouts: {len(mentions)}"


def scout_button_label(subzone_display_name: str) -> str:
    return f"\U0001f50d {subzone_display_name}"


def scout_confirmed(subzone_display_name: str, zone_display_name: str) -> str:
    return f"You're now scouting **{subzone_display_name}** for **{zone_display_name}**."


def scout_cancelled(subzone_display_name: str) -> str:
    return f"You're no longer scouting **{subzone_display_name}**."


FOUND_BUTTON_EMOJI = "\U0001f4cd"  # 📍


def scouting_done_title(zone_display_name: str) -> str:
    return f"{zone_display_name} Scouting - Done"


def scouting_found_note(subzone_display_name: str) -> str:
    return f"**Elite found at {subzone_display_name}**"


def elite_found_title(subzone_display_name: str) -> str:
    return f"\U0001f3af Elite found at {subzone_display_name}!"


def elite_found_description(zone_display_name: str) -> str:
    return f"Spotted in **{zone_display_name}** — go go go!"


def found_confirmed(subzone_display_name: str) -> str:
    return f"Marked **{subzone_display_name}** as found — announcement posted."


UNDO_BUTTON_EMOJI = "\U0001f504"  # 🔄


def found_undone(zone_display_name: str) -> str:
    return f"Undid the Elite Found report for **{zone_display_name}** — scouting re-enabled."


BOSS_KILLED_TITLE = "\U0001f480 Boss killed"
BOSS_KILLED_ZONE_FIELD = "Zone"
BOSS_KILLED_SUBZONE_FIELD = "Sub-zone"
BOSS_KILLED_UNKNOWN_SUBZONE = "Unknown"
BOSS_KILLED_TIME_FIELD = "Killed at"
BOSS_KILLED_REPORTED_BY_FIELD = "Reported by"


KILL_BUTTON_EMOJI = "\U0001f480"  # 💀


# ---------------------------------------------------------------------------
# /elite-killed
# ---------------------------------------------------------------------------


def killed_confirmation(display_name: str, spawn_at_ts: int) -> str:
    return (
        f"Recorded kill for **{display_name}**. Next spawn: "
        f"<t:{spawn_at_ts}:t> (<t:{spawn_at_ts}:R>)."
    )


def killed_invalid_time(raw: str) -> str:
    return (
        f"Couldn't parse time `{raw}`. Use `HH:MM` (today) or `DD/MM HH:MM`, e.g. `21:30` or `14/07 21:30`."
    )


# ---------------------------------------------------------------------------
# /elite-noshow
# ---------------------------------------------------------------------------


def noshow_no_window(display_name: str) -> str:
    return f"**{display_name}** has no pending spawn time to report as a no-show yet. Log a kill first."


def noshow_confirmation(display_name: str, spawn_at_ts: int) -> str:
    return (
        f"No-show recorded for **{display_name}**. Timer pushed back — new spawn time: "
        f"<t:{spawn_at_ts}:t> (<t:{spawn_at_ts}:R>)."
    )


# ---------------------------------------------------------------------------
# /elite-undo
# ---------------------------------------------------------------------------


def undo_nothing_to_undo(display_name: str) -> str:
    return f"There's nothing to undo for **{display_name}**."


def undo_confirmation(display_name: str) -> str:
    return f"Last entry for **{display_name}** has been undone."


# ---------------------------------------------------------------------------
# /elite-status
# ---------------------------------------------------------------------------

STATUS_COMMAND_TITLE = "Elite Boss Status"


def status_row_no_data(display_name: str) -> str:
    return f"**{display_name}**: no kill recorded yet"


def status_row(
    display_name: str,
    last_kill_ts: int,
    spawn_at_ts: int,
    reported_by: str,
    last_kill_subzone: str | None = None,
) -> str:
    subzone_note = f" in **{last_kill_subzone}**" if last_kill_subzone else ""
    return (
        f"**{display_name}**: last kill <t:{last_kill_ts}:R>{subzone_note} by {reported_by} | "
        f"next spawn <t:{spawn_at_ts}:t> (<t:{spawn_at_ts}:R>)"
    )


# ---------------------------------------------------------------------------
# /elite-stats
# ---------------------------------------------------------------------------


def stats_title(display_name: str) -> str:
    return f"Observed intervals — {display_name}"


def stats_no_data(display_name: str) -> str:
    return f"Not enough kill history for **{display_name}** yet to compute intervals."


def stats_interval_line(index: int, hours: int, minutes: int) -> str:
    return f"{index}. {hours}h{minutes:02d}m"


def stats_average_line(configured_cooldown_minutes: int, average_minutes: float) -> str:
    hours = int(average_minutes // 60)
    minutes = int(average_minutes % 60)
    return (
        f"Average observed interval: **{hours}h{minutes:02d}m** "
        f"(configured cooldown: {configured_cooldown_minutes // 60}h{configured_cooldown_minutes % 60:02d}m)"
    )


def stats_deviation_note(delta_minutes: float) -> str:
    direction = "longer" if delta_minutes > 0 else "shorter"
    return (
        f"⚠️ Observed average is {abs(delta_minutes):.0f} minutes {direction} than the configured "
        "cooldown — consider updating it with `/elite-config cooldown`."
    )


# ---------------------------------------------------------------------------
# /elite-zones
# ---------------------------------------------------------------------------

ZONE_LIST_TITLE = "Zones & Sub-zones"
ZONE_LIST_EMPTY = "No zones configured."


def zone_list_entry(display_name: str, subzone_names: list[str]) -> str:
    lines = [f"* {display_name}"]
    lines.extend(f"  * {name}" for name in subzone_names)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------

ZONE_NOT_FOUND = "Unknown zone. Pick one from the autocomplete list."
NO_PERMISSION = "You need the **Manage Server** permission or the configured admin role to use this command."
GENERIC_ERROR = "Something went wrong handling that command. Check the bot logs for details."
GUILD_ONLY = "This command can only be used inside the server."


# ---------------------------------------------------------------------------
# /elite-config
# ---------------------------------------------------------------------------


def config_cooldown_updated(display_name: str, cooldown_minutes: int) -> str:
    hours = cooldown_minutes // 60
    minutes = cooldown_minutes % 60
    return f"Cooldown for **{display_name}** set to {hours}h{minutes:02d}m."


def config_invalid_duration(raw: str) -> str:
    return f"Couldn't parse duration `{raw}`. Use formats like `4h`, `5h30` or `90m`."


def config_channel_updated(channel_mention: str) -> str:
    return f"Perpetual status message will now be posted/updated in {channel_mention}."


def config_alert_channel_updated(channel_mention: str) -> str:
    return f"Spawn alerts will now be posted in {channel_mention}."


def config_alert_channel_cleared() -> str:
    return "Alert channel cleared — spawn alerts will be posted in the status channel instead."


def config_alert_role_updated(role_mention: str) -> str:
    return f"Alert role set to {role_mention}."


def config_alert_role_cleared() -> str:
    return "Alert role cleared — future alerts will not ping any role."


def config_alert_offset_updated(minutes: int) -> str:
    return f"Pre-alert offset set to {minutes} minutes before each window opens."


def config_timezone_updated(tz: str) -> str:
    return f"Timezone set to `{tz}`."


def config_timezone_invalid(tz: str) -> str:
    return f"`{tz}` is not a recognized IANA timezone (e.g. `Europe/Paris`, `UTC`)."


def config_map_updated(display_name: str) -> str:
    return f"Map image updated for **{display_name}**."


def config_map_invalid_type() -> str:
    return "Map image must be a PNG or JPG attachment."


def config_zone_added(display_name: str, cooldown_minutes: int) -> str:
    hours = cooldown_minutes // 60
    minutes = cooldown_minutes % 60
    return f"Zone **{display_name}** added with a {hours}h{minutes:02d}m cooldown."


def config_zone_already_exists(display_name: str) -> str:
    return f"A zone named **{display_name}** already exists."


def config_zone_removed(display_name: str) -> str:
    return f"Zone **{display_name}** and its history have been removed."


def config_sync_zones_added(display_names: list[str]) -> str:
    joined = ", ".join(f"**{name}**" for name in display_names)
    return f"Added missing default zone(s): {joined}."


def config_sync_zones_up_to_date() -> str:
    return "All built-in default zones are already present — nothing to add."


def config_zone_reset(display_name: str) -> str:
    return (
        f"Zone **{display_name}** has been reset — last kill, current window and history "
        "cleared. Cooldown and map are unchanged."
    )


def config_subzone_added(zone_display_name: str, subzone_display_name: str) -> str:
    return f"Sub-zone **{subzone_display_name}** added to **{zone_display_name}**."


def config_subzone_already_exists(zone_display_name: str, subzone_display_name: str) -> str:
    return f"**{zone_display_name}** already has a sub-zone named **{subzone_display_name}**."


def config_subzone_removed(zone_display_name: str, subzone_display_name: str) -> str:
    return f"Sub-zone **{subzone_display_name}** removed from **{zone_display_name}**."


def config_subzone_not_found() -> str:
    return "Unknown sub-zone for that zone. Pick one from the autocomplete list."


def config_submap_updated(zone_display_name: str, subzone_display_name: str) -> str:
    return f"Map image updated for **{subzone_display_name}** ({zone_display_name})."


MAP_NOT_UPLOADED_NOTE = "No map uploaded yet."


def preview_zone_header(zone_display_name: str) -> str:
    return f"\U0001f5fa️ Maps for **{zone_display_name}**"


def config_map_missing(title: str) -> str:
    return f"No map uploaded yet for **{title}**."


def config_preview_failed(title: str) -> str:
    return (
        f"Failed to send the map preview for **{title}** — it may be too large for Discord "
        "to upload. Check the bot logs for details."
    )


def config_reset_maps_done(zone_display_name: str, restored: int, cleared: int) -> str:
    base = f"Reset maps for **{zone_display_name}**: {restored} restored to the bundled default"
    if cleared:
        base += f", {cleared} cleared (no bundled default exists for them)"
    return base + "."


def config_repost_no_channel() -> str:
    return "No channel is configured yet. Set one first with `/elite-config channel`."


def config_repost_confirmation() -> str:
    return "Refreshing the perpetual status message now — it will be recreated if it's missing."


def config_admin_role_updated(role_mention: str) -> str:
    return f"Admin role set to {role_mention} — members with this role can now use `/elite-config`."


def config_admin_role_cleared() -> str:
    return "Admin role cleared — only members with **Manage Server** can now use `/elite-config`."


CONFIG_SHOW_TITLE = "Elite Tracker Configuration"
CONFIG_SHOW_GENERAL_FIELD = "General"
CONFIG_SHOW_ZONES_FIELD = "Zones"
CONFIG_SHOW_NO_ZONES = "No zones configured."


def config_show_channel_line(channel_mention: str | None) -> str:
    return f"**Channel:** {channel_mention}" if channel_mention else "**Channel:** not set"


def config_show_alert_channel_line(channel_mention: str | None) -> str:
    return (
        f"**Alert channel:** {channel_mention}"
        if channel_mention
        else "**Alert channel:** same as status channel"
    )


def config_show_alert_role_line(role_mention: str | None) -> str:
    return f"**Alert role:** {role_mention}" if role_mention else "**Alert role:** none (no ping)"


def config_show_admin_role_line(role_mention: str | None) -> str:
    return (
        f"**Admin role:** {role_mention}"
        if role_mention
        else "**Admin role:** none (Manage Server only)"
    )


def config_show_alert_offset_line(minutes: int) -> str:
    return f"**Pre-alert offset:** {minutes} minutes"


def config_show_timezone_line(tz: str) -> str:
    return f"**Timezone:** `{tz}`"


def config_show_zone_line(
    display_name: str, cooldown_minutes: int, has_map: bool, subzone_count: int
) -> str:
    hours = cooldown_minutes // 60
    minutes = cooldown_minutes % 60
    map_marker = " 🗺️" if has_map else ""
    subzone_note = f" ({subzone_count} sub-zones)" if subzone_count else ""
    return f"**{display_name}** — {hours}h{minutes:02d}m{map_marker}{subzone_note}"


# ---------------------------------------------------------------------------
# Startup / operational log messages (not user-facing in Discord, but kept
# here too so all copy lives in one place)
# ---------------------------------------------------------------------------

LOG_DATA_CORRUPT = "Primary data file is corrupt or unreadable, falling back to backup: %s"
LOG_BACKUP_CORRUPT = "Backup data file is also corrupt or missing, seeding fresh data: %s"
LOG_SEEDED_FRESH = "No existing data file found, seeded fresh data at %s"
LOG_PERPETUAL_MESSAGE_MISSING = "Perpetual message %s not found in channel %s, recreating it"
LOG_CHANNEL_MISSING = "Configured channel %s could not be resolved, skipping perpetual message update"
LOG_MISSING_PERMISSIONS = "Missing permissions to %s in channel %s"
