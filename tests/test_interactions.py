from __future__ import annotations

from bot.interactions import EPHEMERAL_TTL_SECONDS, send_ephemeral, send_reply
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


async def test_send_reply_defaults_to_non_ephemeral_with_no_auto_delete():
    interaction = FakeInteraction()
    await send_reply(interaction, "public message", embed="fake-embed")

    content, kwargs = interaction.response.send_message_calls[0]
    assert content == "public message"
    assert kwargs["ephemeral"] is False
    assert kwargs["delete_after"] is None
    assert kwargs["embed"] == "fake-embed"


async def test_send_reply_via_followup_does_not_schedule_a_delete():
    interaction = FakeInteraction()
    await interaction.response.defer()

    await send_reply(interaction, "public followup")

    content, kwargs = interaction.followup.sent[0]
    assert content == "public followup"
    assert kwargs["ephemeral"] is False
    message = interaction.followup.messages[0]
    assert message.delete_delays == []
    assert message.deleted is False
