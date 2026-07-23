"""Process-level environment configuration (secrets), distinct from the
in-game/guild configuration stored in elite.json."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class EnvConfig:
    discord_token: str
    owner_guild_id: int


def load_env_config() -> EnvConfig:
    """Read DISCORD_TOKEN / OWNER_GUILD_ID from the environment.

    The bot is installable on any number of guilds (see bot/main.py);
    OWNER_GUILD_ID no longer limits which server it runs on — it designates
    the one server allowed to edit the shared zone/cooldown/map/fallback
    settings (see bot/cogs/admin_commands.py's owner-only gating), and is
    where a pre-existing single-guild install's settings get filed on first
    boot after an upgrade (see bot/storage.py's v14->v15 migration).

    Calls load_dotenv() first, which is a no-op when no .env file is present
    (the normal case under Portainer, where these come from the stack's
    environment variables instead).
    """
    load_dotenv()

    token = os.environ.get("DISCORD_TOKEN")
    owner_guild_id_raw = os.environ.get("OWNER_GUILD_ID")

    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set")
    if not owner_guild_id_raw:
        raise RuntimeError("OWNER_GUILD_ID environment variable is not set")
    try:
        owner_guild_id = int(owner_guild_id_raw)
    except ValueError as exc:
        raise RuntimeError(f"OWNER_GUILD_ID must be an integer, got {owner_guild_id_raw!r}") from exc

    return EnvConfig(discord_token=token, owner_guild_id=owner_guild_id)
