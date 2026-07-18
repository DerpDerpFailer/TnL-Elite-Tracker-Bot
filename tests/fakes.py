"""Lightweight fake Discord objects for testing interaction-driven code
without a live gateway connection. Mirrors just enough of discord.py's shape
(message.edit/delete, interaction.response, interaction.followup) for
bot/scouting.py and bot/interactions.py to exercise their real logic."""
from __future__ import annotations

_next_message_id = 100_000


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


class FakeInteraction:
    def __init__(self, message: FakeMessage | None = None, user: FakeUser | None = None) -> None:
        self.response = FakeInteractionResponse()
        self.followup = FakeFollowup()
        self.message = message
        self.user = user or FakeUser()


class FakeBot:
    """Minimal stand-in for EliteBot: only what bot/scouting.py needs
    (.storage, .get_channel, .fetch_channel)."""

    def __init__(self, storage, channel: FakeChannel) -> None:
        self.storage = storage
        self._channel = channel

    def get_channel(self, channel_id: int):
        return self._channel if channel_id == self._channel.id else None

    async def fetch_channel(self, channel_id: int):
        return self._channel
