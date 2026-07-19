from __future__ import annotations

from bot.cogs.admin_commands import AdminConfigGroup
from tests.fakes import FakeInteraction


def _cog(bot) -> AdminConfigGroup:
    return AdminConfigGroup(bot)


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

    async def test_unknown_zone_reports_error(self, bot, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.cogs.admin_commands.MAPS_DIR", tmp_path)
        cog = _cog(bot)
        interaction = FakeInteraction()

        await cog.preview_zone.callback(cog, interaction, "nowhere")

        content, _ = interaction.response.send_message_calls[0]
        assert content == "Unknown zone. Pick one from the autocomplete list."
