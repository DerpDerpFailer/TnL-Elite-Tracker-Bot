from __future__ import annotations

import discord

from bot.cogs.admin_commands import AdminConfigGroup
from tests.fakes import FakeInteraction


def _cog(bot) -> AdminConfigGroup:
    return AdminConfigGroup(bot)


class _FakeTooLargeResponse:
    status = 413
    reason = "Payload Too Large"
    headers = {}


class TestPreviewMap:
    async def test_shows_the_zone_level_map_when_it_exists(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        (tmp_path / "laslan.png").write_bytes(b"fake-png-bytes")
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_map.callback(cog, interaction, "laslan", None)

        content, kwargs = interaction.response.send_message_calls[0]
        assert kwargs["embed"].title == "Laslan"
        assert kwargs["embed"].image.url == "attachment://laslan.png"
        assert kwargs["file"].filename == "laslan.png"
        assert kwargs["ephemeral"] is False  # visible to the whole channel

    async def test_shows_a_subzone_map_when_it_exists(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        (tmp_path / "laslan__urstella-fields.png").write_bytes(b"fake-png-bytes")
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_map.callback(cog, interaction, "laslan", "urstella-fields")

        content, kwargs = interaction.response.send_message_calls[0]
        assert kwargs["embed"].title == "Urstella Fields"
        assert kwargs["embed"].image.url == "attachment://laslan__urstella-fields.png"

    async def test_reports_when_no_map_uploaded_yet(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_map.callback(cog, interaction, "laslan", None)

        content, kwargs = interaction.response.send_message_calls[0]
        assert "No map uploaded" in content
        assert "embed" not in kwargs

    async def test_unknown_zone_reports_error(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_map.callback(cog, interaction, "nowhere", None)

        content, _ = interaction.response.send_message_calls[0]
        assert content == "Unknown zone. Pick one from the autocomplete list."

    async def test_reports_a_graceful_error_when_the_upload_fails(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        (tmp_path / "laslan.png").write_bytes(b"fake-png-bytes")
        cog = _cog(bot)
        interaction = FakeInteraction()

        real_send_message = interaction.response.send_message
        calls = {"n": 0}

        async def flaky_send_message(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise discord.HTTPException(_FakeTooLargeResponse(), "Payload too large")
            return await real_send_message(*args, **kwargs)

        interaction.response.send_message = flaky_send_message

        await cog.preview_map.callback(cog, interaction, "laslan", None)

        # the first (failed) attempt carried the embed/file; the fallback is
        # a plain text error, proving the command didn't just crash
        content, kwargs = interaction.response.send_message_calls[0]
        assert "embed" not in kwargs
        assert "too large" in content.lower()

    async def test_unknown_subzone_reports_error(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_map.callback(cog, interaction, "laslan", "nowhere")

        content, _ = interaction.response.send_message_calls[0]
        assert "Unknown sub-zone" in content


class TestPreviewZone:
    async def test_lists_zone_map_and_every_subzone_noting_missing_ones(
        self, bot, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        (tmp_path / "nix.png").write_bytes(b"fake-png-bytes")
        (tmp_path / "nix__frozen-nightlands.png").write_bytes(b"fake-png-bytes")
        # every other Nix sub-zone map is intentionally left missing
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_zone.callback(cog, interaction, "nix")

        content, kwargs = interaction.response.send_message_calls[0]
        assert "Nix" in content
        embeds = kwargs["embeds"]
        assert len(embeds) == 6  # zone map + 5 sub-zones
        by_title = {e.title: e for e in embeds}
        assert by_title["Nix"].image.url == "attachment://nix.png"
        assert by_title["Frozen Nightlands"].image.url == "attachment://nix__frozen-nightlands.png"
        assert by_title["Border Zone"].description == "No map uploaded yet."
        assert len(kwargs["files"]) == 2
        assert kwargs["ephemeral"] is False  # visible to the whole channel

    async def test_chunks_across_messages_when_more_than_ten_images(
        self, bot, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        cog = _cog(bot)
        interaction = FakeInteraction()

        # talandre-dungeon has 10 sub-zones + its own zone map = 11 entries
        await cog.preview_zone.callback(cog, interaction, "talandre-dungeon")

        first_content, first_kwargs = interaction.response.send_message_calls[0]
        assert len(first_kwargs["embeds"]) == 10
        assert len(interaction.followup.sent) == 1
        second_content, second_kwargs = interaction.followup.sent[0]
        assert len(second_kwargs["embeds"]) == 1
        assert second_content is None  # only the first chunk carries the header

    async def test_reports_a_graceful_error_when_a_chunk_upload_fails(
        self, bot, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        cog = _cog(bot)
        interaction = FakeInteraction()

        real_send_message = interaction.response.send_message

        async def flaky_send_message(*args, **kwargs):
            if "embeds" in kwargs:
                raise discord.HTTPException(_FakeTooLargeResponse(), "Payload too large")
            return await real_send_message(*args, **kwargs)

        interaction.response.send_message = flaky_send_message

        # syleus has no sub-zones, so this is a single-chunk, single-embed call
        await cog.preview_zone.callback(cog, interaction, "syleus")

        content, kwargs = interaction.response.send_message_calls[0]
        assert "embeds" not in kwargs
        assert "too large" in content.lower()

    async def test_unknown_zone_reports_error(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_zone.callback(cog, interaction, "nowhere")

        content, _ = interaction.response.send_message_calls[0]
        assert content == "Unknown zone. Pick one from the autocomplete list."


class TestResetMaps:
    async def test_delegates_to_restore_bundled_defaults_for_zone_and_reports_result(
        self, bot, monkeypatch
    ):
        calls = []

        def fake_restore(zone_key, subzone_keys, maps_dir=None):
            calls.append((zone_key, sorted(subzone_keys)))
            return (3, 1)

        monkeypatch.setattr(
            "bot.cogs.admin_commands.restore_bundled_defaults_for_zone", fake_restore
        )
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.reset_maps.callback(cog, interaction, "nix")

        assert calls == [
            ("nix", ["border-zone", "entropic-tundra", "frozen-nightlands", "stillreach", "tumgir-hollow"])
        ]
        content, kwargs = interaction.response.send_message_calls[0]
        assert content == "Reset maps for **Nix**: 3 restored to the bundled default, 1 cleared (no bundled default exists for them)."
        assert kwargs["ephemeral"] is True

    async def test_unknown_zone_reports_error(self, bot, monkeypatch):
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.reset_maps.callback(cog, interaction, "nowhere")

        content, _ = interaction.response.send_message_calls[0]
        assert content == "Unknown zone. Pick one from the autocomplete list."
