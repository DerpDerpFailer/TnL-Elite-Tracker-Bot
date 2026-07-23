"""Lightweight fake Discord objects for testing interaction-driven code
without a live gateway connection. Mirrors just enough of discord.py's shape
(message.edit/delete, interaction.response, interaction.followup) for
bot/scouting.py and bot/interactions.py to exercise their real logic."""
from __future__ import annotations

import discord

from bot.models import build_guild_config

_next_message_id = 100_000

# Most tests exercise exactly one installed guild — FakeBot registers this as
# its owner guild (and channel_id, by default) so single-guild test call
# sites don't need to wire that up by hand. Multi-guild tests pass their own
# guild ids and/or call add_channel/register additional guilds explicitly.
DEFAULT_GUILD_ID = 42


class FakeMessage:
    def __init__(self) -> None:
        global _next_message_id
        _next_message_id += 1
        self.id = _next_message_id
        self.edits: list[dict] = []
        self.deleted = False
        self.delete_delays: list[float | None] = []

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)

    async def delete(self, delay: float | None = None) -> None:
        self.deleted = True
        self.delete_delays.append(delay)


class FakeChannel:
    def __init__(self, channel_id: int = 999) -> None:
        self.id = channel_id
        self.sent: list[dict] = []
        self.messages: dict[int, FakeMessage] = {}

    async def send(self, **kwargs) -> FakeMessage:
        msg = FakeMessage()
        self.sent.append(kwargs)
        self.messages[msg.id] = msg
        return msg

    async def fetch_message(self, message_id: int) -> FakeMessage:
        return self.messages[message_id]


class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.messages: list[FakeMessage] = []

    async def send(self, content=None, wait: bool = False, **kwargs) -> FakeMessage | None:
        self.sent.append((content, {**kwargs, "wait": wait}))
        if not wait:
            return None
        msg = FakeMessage()
        self.messages.append(msg)
        return msg


class FakeInteractionResponse:
    def __init__(self) -> None:
        self._done = False
        self.send_message_calls: list[tuple] = []
        self.edit_message_calls: list[dict] = []
        self.defer_calls = 0

    def is_done(self) -> bool:
        return self._done

    async def defer(self, ephemeral: bool = False) -> None:
        self._done = True
        self.defer_calls += 1

    async def send_message(self, content=None, **kwargs) -> None:
        self._done = True
        self.send_message_calls.append((content, kwargs))

    async def edit_message(self, **kwargs) -> None:
        self._done = True
        self.edit_message_calls.append(kwargs)


class FakeUser:
    def __init__(
        self, user_id: int = 555, display_name: str = "Tester", tag: str = "Tester#0001"
    ) -> None:
        self.id = user_id
        self.display_name = display_name
        self._tag = tag

    def __str__(self) -> str:
        return self._tag


class _FakeErrorResponse:
    status = 404
    reason = "Not Found"
    headers = {}


class FakeInteraction:
    def __init__(
        self,
        message: FakeMessage | None = None,
        user: FakeUser | None = None,
        guild_id: int = DEFAULT_GUILD_ID,
    ) -> None:
        self.response = FakeInteractionResponse()
        self.followup = FakeFollowup()
        self.message = message
        self.user = user or FakeUser()
        self.guild_id = guild_id


class FakeBot:
    """Minimal stand-in for EliteBot: only what bot/scouting.py & friends need
    (.storage, .owner_guild_id, .get_channel, .fetch_channel).

    By default also registers `channel` as DEFAULT_GUILD_ID's configured
    channel (status + alert), since most tests exercise exactly one
    installed guild — pass register_guild=False to start with no guild
    installed/configured, or call add_channel/register more guilds by hand
    for multi-guild scenarios."""

    def __init__(
        self,
        storage,
        channel: FakeChannel,
        *,
        owner_guild_id: int = DEFAULT_GUILD_ID,
        register_guild: bool = True,
    ) -> None:
        self.storage = storage
        self.owner_guild_id = owner_guild_id
        self._channels: dict[int, FakeChannel] = {channel.id: channel}
        if register_guild:
            guild_config = storage.data["guilds"].setdefault(
                str(owner_guild_id), build_guild_config()
            )
            guild_config["channel_id"] = channel.id

    def add_channel(self, channel: FakeChannel) -> None:
        self._channels[channel.id] = channel

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)

    async def fetch_channel(self, channel_id: int):
        channel = self._channels.get(channel_id)
        if channel is None:
            raise discord.HTTPException(_FakeErrorResponse(), "Unknown channel")
        return channel
