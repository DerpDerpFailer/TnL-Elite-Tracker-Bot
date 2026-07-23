from __future__ import annotations

import time

from bot.models import build_guild_config
from bot.perpetual_message import PerpetualMessageManager
from tests.fakes import FakeChannel


class TestPerpetualMessageMultiGuild:
    async def test_sync_posts_a_copy_into_every_installed_guilds_channel(self, storage, channel, bot):
        other_channel = FakeChannel(channel_id=222)
        bot.add_channel(other_channel)
        other_guild_config = build_guild_config()
        other_guild_config["channel_id"] = other_channel.id
        storage.data["guilds"]["999"] = other_guild_config

        mgr = PerpetualMessageManager(storage)
        await mgr.force_update(bot, time.time())

        assert len(channel.sent) == 1
        assert len(other_channel.sent) == 1
        own_message_id = storage.data["guilds"][str(bot.owner_guild_id)]["perpetual_message_id"]
        other_message_id = storage.data["guilds"]["999"]["perpetual_message_id"]
        assert own_message_id is not None and other_message_id is not None
        assert own_message_id != other_message_id
        assert own_message_id in channel.messages
        assert other_message_id in other_channel.messages

    async def test_second_sync_edits_each_guilds_existing_message_instead_of_reposting(
        self, storage, channel, bot
    ):
        other_channel = FakeChannel(channel_id=222)
        bot.add_channel(other_channel)
        other_guild_config = build_guild_config()
        other_guild_config["channel_id"] = other_channel.id
        storage.data["guilds"]["999"] = other_guild_config

        mgr = PerpetualMessageManager(storage)
        await mgr.force_update(bot, time.time())
        await mgr.force_update(bot, time.time() + 60)

        assert len(channel.sent) == 1  # no second send
        assert len(other_channel.sent) == 1
        own_message_id = storage.data["guilds"][str(bot.owner_guild_id)]["perpetual_message_id"]
        other_message_id = storage.data["guilds"]["999"]["perpetual_message_id"]
        assert channel.messages[own_message_id].edits
        assert other_channel.messages[other_message_id].edits

    async def test_a_guild_with_no_channel_configured_is_skipped(self, storage, channel, bot):
        storage.data["guilds"]["999"] = build_guild_config()  # channel_id stays None

        mgr = PerpetualMessageManager(storage)
        await mgr.force_update(bot, time.time())

        assert len(channel.sent) == 1
        assert storage.data["guilds"]["999"]["perpetual_message_id"] is None
