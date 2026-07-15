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
    ZonePhase.ACTIVE: "\U0001f7e2",  # 🟢 spawn window is currently open
    ZonePhase.IMMINENT: "\U0001f7e1",  # 🟡 window opens in under 30 minutes
    ZonePhase.WAITING: "⚪",  # ⚪ waiting for cooldown to elapse
    ZonePhase.NO_DATA: "❓",  # ❓ no kill has ever been recorded
}

STATUS_EMBED_TITLE = "Elite Boss Timers"
STATUS_EMBED_DESCRIPTION = "Live respawn windows for every tracked Elite PvP zone."
STATUS_EMBED_FOOTER = "Use /elite-killed to report a kill"


def status_embed_updated_line(updated_ts: int) -> str:
    return f"Last updated <t:{updated_ts}:R>"


def zone_line_no_data(emoji: str, display_name: str) -> str:
    return f"{emoji} **{display_name}** — no kill recorded yet"


def zone_line(
    emoji: str,
    display_name: str,
    last_kill_ts: int,
    window_start_ts: int,
    window_end_ts: int,
) -> str:
    return (
        f"{emoji} **{display_name}** — last kill <t:{last_kill_ts}:R>\n"
        f"⤷ next window <t:{window_start_ts}:t> → <t:{window_end_ts}:t> "
        f"(<t:{window_start_ts}:R>)"
    )


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

MAP_REMINDER_NOTE = (
    "Reminder: the in-game map icon only appears once you're close to the spawn point, "
    "and the red pillar shows up about 1 minute before the boss actually spawns."
)


def pre_alert_title(display_name: str) -> str:
    return f"⏰ {display_name} spawn window incoming"


def pre_alert_description(window_start_ts: int, window_end_ts: int, offset_minutes: int) -> str:
    return (
        f"Spawn window opens in about {offset_minutes} minutes: "
        f"<t:{window_start_ts}:t> → <t:{window_end_ts}:t> (<t:{window_start_ts}:R>)"
    )


def start_alert_title(display_name: str) -> str:
    return f"\U0001f6a8 {display_name} spawn window is OPEN"


def start_alert_description(window_start_ts: int, window_end_ts: int) -> str:
    return (
        f"Spawn possible **now** (7-minute window): "
        f"<t:{window_start_ts}:t> → <t:{window_end_ts}:t>"
    )


# ---------------------------------------------------------------------------
# /elite-killed
# ---------------------------------------------------------------------------


def killed_confirmation(display_name: str, window_start_ts: int, window_end_ts: int) -> str:
    return (
        f"Recorded kill for **{display_name}**. Next window: "
        f"<t:{window_start_ts}:t> → <t:{window_end_ts}:t> (<t:{window_start_ts}:R>)."
    )


def killed_invalid_time(raw: str) -> str:
    return (
        f"Couldn't parse time `{raw}`. Use `HH:MM` (today) or `DD/MM HH:MM`, e.g. `21:30` or `14/07 21:30`."
    )


# ---------------------------------------------------------------------------
# /elite-noshow
# ---------------------------------------------------------------------------


def noshow_no_window(display_name: str) -> str:
    return f"**{display_name}** has no active window to report as a no-show yet. Log a kill first."


def noshow_confirmation(display_name: str, window_start_ts: int, window_end_ts: int) -> str:
    return (
        f"No-show recorded for **{display_name}**. Timer pushed back — new window: "
        f"<t:{window_start_ts}:t> → <t:{window_end_ts}:t> (<t:{window_start_ts}:R>)."
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


def status_row(display_name: str, last_kill_ts: int, window_start_ts: int, window_end_ts: int, reported_by: str) -> str:
    return (
        f"**{display_name}**: last kill <t:{last_kill_ts}:R> by {reported_by} | "
        f"next window <t:{window_start_ts}:t> → <t:{window_end_ts}:t>"
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


def config_admin_role_updated(role_mention: str) -> str:
    return f"Admin role set to {role_mention} — members with this role can now use `/elite-config`."


def config_admin_role_cleared() -> str:
    return "Admin role cleared — only members with **Manage Server** can now use `/elite-config`."


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
