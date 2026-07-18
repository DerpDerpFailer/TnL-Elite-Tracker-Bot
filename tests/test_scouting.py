from __future__ import annotations

from bot import domain
from bot.alerts import AlertManager
from bot.models import build_seed_data
from bot.perpetual_message import PerpetualMessageManager
from bot.scouting import (
    NO_SUBZONE_KEY,
    ScoutingView,
    build_boss_killed_embed,
    build_elite_found_embed,
    build_scouting_embed,
    chunk_subzone_keys,
)
from tests.fakes import FakeInteraction, FakeUser


class TestChunkSubzoneKeys:
    def test_splits_into_chunks_of_five(self):
        zone = build_seed_data()["zones"]["stonegard"]  # 8 sub-zones
        assert [len(c) for c in chunk_subzone_keys(zone)] == [5, 3]

    def test_no_subzones_gives_no_chunks(self):
        zone = build_seed_data()["zones"]["syleus"]
        assert chunk_subzone_keys(zone) == []

    def test_exactly_five_is_a_single_chunk(self):
        zone = build_seed_data()["zones"]["nix"]  # 5 sub-zones
        assert [len(c) for c in chunk_subzone_keys(zone)] == [5]


class TestEmbeds:
    def test_scouting_embed_lists_all_subzones_plus_reminder(self, storage):
        embed = build_scouting_embed(storage, "laslan")
        assert len(embed.fields) == 8  # 7 sub-zones + the map reminder field
        assert "Urstella Fields" in [f.name for f in embed.fields]

    def test_scouting_embed_spawn_due_variant_has_different_title(self, storage):
        domain.record_kill(storage.data, "laslan", 1000.0, 1, "tester")
        not_due = build_scouting_embed(storage, "laslan", spawn_due=False)
        due = build_scouting_embed(storage, "laslan", spawn_due=True)
        assert due.title != not_due.title
        assert "Spawn Due" in due.title

    def test_elite_found_embed_names_the_subzone(self, storage):
        embed, file = build_elite_found_embed(storage, "laslan", "urstella-fields")
        assert "Urstella Fields" in embed.title
        assert file is None  # no map uploaded in this test

    def test_boss_killed_embed_fields(self):
        embed = build_boss_killed_embed("Laslan", "Urstella Fields", 1700000000.0, 555)
        values = {f.name: f.value for f in embed.fields}
        assert values["Zone"] == "Laslan"
        assert values["Sub-zone"] == "Urstella Fields"
        assert values["Reported by"] == "<@555>"

    def test_boss_killed_embed_unknown_subzone_falls_back(self):
        embed = build_boss_killed_embed("Syleus", None, 1700000000.0, 555)
        values = {f.name: f.value for f in embed.fields}
        assert values["Sub-zone"] == "Unknown"


class TestScoutingViewLayout:
    def test_one_row_per_subzone_with_kill_button(self, bot, storage):
        subzone_keys = list(storage.data["zones"]["nix"]["subzones"].keys())
        view = ScoutingView(bot, "nix", subzone_keys, show_kill_button=True)
        assert len(view.children) == len(subzone_keys) * 3
        assert {item.row for item in view.children} == set(range(len(subzone_keys)))

    def test_no_kill_button_by_default(self, bot, storage):
        subzone_keys = list(storage.data["zones"]["nix"]["subzones"].keys())
        view = ScoutingView(bot, "nix", subzone_keys)
        assert len(view.children) == len(subzone_keys) * 2

    def test_zero_subzone_zone_gets_one_generic_kill_button(self, bot):
        view = ScoutingView(bot, "syleus", [], show_kill_button=True)
        assert len(view.children) == 1
        assert view.children[0].custom_id.endswith(f":{NO_SUBZONE_KEY}")

    def test_zero_subzone_zone_without_kill_button_has_nothing(self, bot):
        view = ScoutingView(bot, "syleus", [])
        assert len(view.children) == 0


async def _send_pre_alert(mgr, bot, channel, zone_key):
    zone = bot.storage.data["zones"][zone_key]
    await mgr._send_pre_alert(bot, channel, zone_key, zone, role_mention=None)
    return zone


class TestScoutClick:
    async def test_toggle_adds_then_removes_scout_and_updates_embed(self, bot, storage, channel):
        mgr = AlertManager(storage, PerpetualMessageManager(storage))
        domain.record_kill(storage.data, "nix", 1000.0, 1, "tester")
        zone = await _send_pre_alert(mgr, bot, channel, "nix")

        primary_msg = channel.messages[zone["scouting_messages"][0]["message_id"]]
        view = channel.sent[0]["view"]
        subzone_key = list(zone["subzones"].keys())[0]
        user = FakeUser(user_id=111)

        interaction = FakeInteraction(message=primary_msg, user=user)
        await view._on_scout_click(interaction, subzone_key)
        assert zone["subzones"][subzone_key]["scouts"] == [111]
        # a click on the primary message edits it in place via the
        # interaction response itself (edit_message), not message.edit()
        assert interaction.response.edit_message_calls, "should edit in place"

        await view._on_scout_click(FakeInteraction(message=primary_msg, user=user), subzone_key)
        assert zone["subzones"][subzone_key]["scouts"] == []


class TestFoundAndUndo:
    async def test_found_disables_scout_and_found_but_not_kill(self, bot, storage, channel):
        mgr = AlertManager(storage, PerpetualMessageManager(storage))
        domain.record_kill(storage.data, "nix", 1000.0, 1, "tester")
        zone = await _send_pre_alert(mgr, bot, channel, "nix")
        await mgr._mark_spawn_due(bot, "nix", zone)  # adds the kill button
        primary_msg = channel.messages[zone["scouting_messages"][0]["message_id"]]

        subzone_key = list(zone["subzones"].keys())[0]
        view = primary_msg.edits[-1]["view"]
        await view._on_found_click(FakeInteraction(message=primary_msg), subzone_key)

        assert zone["found_this_cycle"] is True
        assert zone["found_announcement_message"] is not None
        final_view = primary_msg.edits[-1]["view"]
        by_emoji = {str(item.emoji): item.disabled for item in final_view.children if item.emoji}
        assert by_emoji["📍"] is True
        assert by_emoji["💀"] is False  # finding isn't killing
        assert "Scouting - Done" in primary_msg.edits[-1]["embed"].title

    async def test_undo_reenables_buttons_and_deletes_announcement(self, bot, storage, channel):
        mgr = AlertManager(storage, PerpetualMessageManager(storage))
        domain.record_kill(storage.data, "nix", 1000.0, 1, "tester")
        zone = await _send_pre_alert(mgr, bot, channel, "nix")
        await mgr._mark_spawn_due(bot, "nix", zone)
        primary_msg = channel.messages[zone["scouting_messages"][0]["message_id"]]

        subzone_key = list(zone["subzones"].keys())[0]
        view = primary_msg.edits[-1]["view"]
        await view._on_found_click(FakeInteraction(message=primary_msg), subzone_key)

        found_msg = channel.messages[zone["found_announcement_message"]["message_id"]]
        found_view = channel.sent[-1]["view"]
        await found_view._on_undo_click(FakeInteraction(message=found_msg))

        assert zone["found_this_cycle"] is False
        assert zone["found_announcement_message"] is None
        assert found_msg.deleted is True
        reenabled_view = primary_msg.edits[-1]["view"]
        assert all(not item.disabled for item in reenabled_view.children)

    async def test_kill_via_announcement_deletes_everything_and_posts_summary(
        self, bot, storage, channel
    ):
        mgr = AlertManager(storage, PerpetualMessageManager(storage))
        domain.record_kill(storage.data, "nix", 1000.0, 1, "tester")
        zone = await _send_pre_alert(mgr, bot, channel, "nix")
        await mgr._mark_spawn_due(bot, "nix", zone)
        primary_msg = channel.messages[zone["scouting_messages"][0]["message_id"]]

        subzone_key = list(zone["subzones"].keys())[0]
        subzone_name = zone["subzones"][subzone_key]["display_name"]
        view = primary_msg.edits[-1]["view"]
        await view._on_found_click(FakeInteraction(message=primary_msg), subzone_key)

        found_msg = channel.messages[zone["found_announcement_message"]["message_id"]]
        found_view = channel.sent[-1]["view"]
        killer = FakeUser(user_id=777, tag="Killer#0002")
        await found_view._on_kill_click(FakeInteraction(message=found_msg, user=killer))

        assert primary_msg.deleted is True
        assert found_msg.deleted is True
        boss_killed = channel.sent[-1]["embed"]
        assert boss_killed.title == "\U0001f480 Boss killed"
        values = {f.name: f.value for f in boss_killed.fields}
        assert values["Zone"] == "Nix"
        assert values["Sub-zone"] == subzone_name
        assert values["Reported by"] == "<@777>"
        # the zone is reset for the next cycle
        assert zone["scouting_messages"] == []
        assert zone["found_announcement_message"] is None
        assert zone["found_this_cycle"] is False


class TestKillFromScoutingMessage:
    async def test_kill_from_continuation_message_deletes_both_messages(
        self, bot, storage, channel
    ):
        mgr = AlertManager(storage, PerpetualMessageManager(storage))
        domain.record_kill(storage.data, "stonegard", 1000.0, 1, "tester")  # 8 sub-zones -> 2 msgs
        zone = await _send_pre_alert(mgr, bot, channel, "stonegard")
        await mgr._mark_spawn_due(bot, "stonegard", zone)

        primary_msg = channel.messages[zone["scouting_messages"][0]["message_id"]]
        continuation_msg = channel.messages[zone["scouting_messages"][1]["message_id"]]
        subzone_key = zone["scouting_messages"][1]["subzone_keys"][0]
        subzone_name = zone["subzones"][subzone_key]["display_name"]
        continuation_view = continuation_msg.edits[-1]["view"]

        await continuation_view._on_kill_click(
            FakeInteraction(message=continuation_msg), subzone_key
        )

        assert primary_msg.deleted is True
        assert continuation_msg.deleted is True
        assert zone["last_kill_subzone"] == subzone_name
