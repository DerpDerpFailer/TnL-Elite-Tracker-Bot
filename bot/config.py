"""Process-level environment configuration (secrets), distinct from the
in-game/guild configuration stored in elite.json."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class EnvConfig:
    discord_token: str
    guild_id: int


def load_env_config() -> EnvConfig:
    """Read DISCORD_TOKEN / GUILD_ID from the environment.

    Calls load_dotenv() first, which is a no-op when no .env file is present
    (the normal case under Portainer, where these come from the stack's
    environment variables instead).
    """
    load_dotenv()

    token = os.environ.get("DISCORD_TOKEN")
    guild_id_raw = os.environ.get("GUILD_ID")

    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set")
    if not guild_id_raw:
        raise RuntimeError("GUILD_ID environment variable is not set")
    try:
        guild_id = int(guild_id_raw)
    except ValueError as exc:
        raise RuntimeError(f"GUILD_ID must be an integer, got {guild_id_raw!r}") from exc

    return EnvConfig(discord_token=token, guild_id=guild_id)
