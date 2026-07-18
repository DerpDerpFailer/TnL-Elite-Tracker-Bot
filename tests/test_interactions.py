from __future__ import annotations

from bot.interactions import EPHEMERAL_TTL_SECONDS, send_ephemeral
from tests.fakes import FakeInteraction


async def test_send_ephemeral_uses_initial_response_with_delete_after():
    interaction = FakeInteraction()
    await send_ephemeral(interaction, "hello")

    content, kwargs = interaction.response.send_message_calls[0]
    assert content == "hello"
    assert kwargs["ephemeral"] is True
    assert kwargs["delete_after"] == EPHEMERAL_TTL_SECONDS
    assert interaction.followup.sent == []


async def test_send_ephemeral_uses_followup_and_schedules_delete_after_defer():
    interaction = FakeInteraction()
    await interaction.response.defer(ephemeral=True)

    await send_ephemeral(interaction, "world")

    content, kwargs = interaction.followup.sent[0]
    assert content == "world"
    assert kwargs["ephemeral"] is True
    assert kwargs["wait"] is True
    assert interaction.followup.messages[0].delete_delays == [EPHEMERAL_TTL_SECONDS]


async def test_send_ephemeral_passes_through_extra_kwargs():
    interaction = FakeInteraction()
    await send_ephemeral(interaction, "with an embed", embed="fake-embed")

    _, kwargs = interaction.response.send_message_calls[0]
    assert kwargs["embed"] == "fake-embed"
