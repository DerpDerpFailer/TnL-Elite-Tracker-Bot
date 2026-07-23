"""Atomic, single-file JSON persistence for /data/elite.json.

Writes never touch the destination path directly: data is written to a
temp file in the same directory, fsynced, and swapped in with os.replace so a
crash mid-write can never leave a truncated/corrupt elite.json. The previous
version is copied to elite.json.bak before each swap.

Locking is split by scope: `Storage.lock` guards structural/config changes
that aren't tied to one zone (adding/removing a zone, `/elite-config`
settings), while `Storage.zone_lock(key)` returns a lock scoped to a single
zone, used by everything that reads/mutates just that zone's state (kill,
no-show, undo, scouting/found/kill buttons, spawn alerts). Callers acquire
the appropriate lock, mutate `self.data`, then call `await storage.save()`
(which does not itself require the caller to hold any particular lock — the
actual file write is separately serialized internally, since it touches the
whole document regardless of which zone changed).

Per-zone locks mean a slow sequence of Discord API calls for one zone (e.g.
deleting several scouting messages after a kill) never blocks a command or
button click for an unrelated zone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from bot import strings
from bot.constants import BACKUP_FILE, DATA_FILE, DEFAULT_SUBZONES, SCHEMA_VERSION
from bot.models import RootData, build_guild_config, build_seed_data, build_subzone_state
from bot.scouting import chunk_subzone_keys
from bot.slugs import slugify

logger = logging.getLogger(__name__)

# --- v9 -> v10 migration data: a handful of dungeon sub-zones were tracked
# under the wrong "1B" vs "B1" pattern or not tracked at all, worked out from
# the actual in-game floor images (see bot/default_maps.py). Brand new
# installs already seed the corrected names directly (bot/constants.py); this
# only matters for a data file seeded before this fix.
_V10_SUBZONE_REMOVALS: list[tuple[str, str]] = [
    ("laslan-dungeon", "Syleus 1F"),
    ("laslan-dungeon", "Syleus 2F"),
    ("laslan-dungeon", "Syleus 3F"),
    ("laslan-dungeon", "Syleus 4F"),
    ("laslan-dungeon", "Syleus 5F"),
    ("stonegard-dungeon", "Sylaveth 1F"),
    ("stonegard-dungeon", "Sylaveth 2F"),
    ("nix", "Scar of Sacrifice"),
]

_V10_SUBZONE_RENAMES: list[tuple[str, str, str]] = [
    ("laslan-dungeon", "Shadowed Crypt 1B", "Shadowed Crypt B1"),
    ("stonegard-dungeon", "Sanctum 1B", "Sanctum B1"),
    ("talandre-dungeon", "Bercant 1B", "Bercant B1"),
    ("talandre-dungeon", "Crimson 1B", "Crimson B1"),
    ("talandre-dungeon", "Crimson 2B", "Crimson B2"),
    ("talandre-dungeon", "Crimson 3B", "Crimson B3"),
    ("talandre-dungeon", "Temple of Truth 1B", "Temple of Truth B1"),
    ("talandre-dungeon", "Temple of Truth 2B", "Temple of Truth B2"),
]

_V10_SUBZONE_ADDITIONS: list[tuple[str, str]] = [
    ("laslan-dungeon", "Syleus B1"),
    ("laslan-dungeon", "Syleus B2"),
    ("laslan-dungeon", "Syleus B3"),
    ("laslan-dungeon", "Syleus B4"),
    ("laslan-dungeon", "Syleus B5"),
    ("laslan-dungeon", "Syleus B6"),
    ("stonegard-dungeon", "Sylaveth B1"),
    ("stonegard-dungeon", "Sylaveth B2"),
    ("talandre-dungeon", "Crimson 1F"),
    ("talandre-dungeon", "Temple of Truth 1F"),
    ("nix", "Border Zone"),
]


class Storage:
    def __init__(self, path: Path = DATA_FILE, backup_path: Path = BACKUP_FILE) -> None:
        self.path = path
        self.backup_path = backup_path
        self.lock = asyncio.Lock()
        self._zone_locks: dict[str, asyncio.Lock] = {}
        self._write_lock = asyncio.Lock()
        self.data: RootData = build_seed_data()

    def zone_lock(self, zone_key: str) -> asyncio.Lock:
        """Lock scoped to a single zone's kill/scout/found/undo/alert flow.
        Created lazily and kept for the process lifetime — the number of
        zones is small and bounded, so there's no meaningful growth."""
        lock = self._zone_locks.get(zone_key)
        if lock is None:
            lock = asyncio.Lock()
            self._zone_locks[zone_key] = lock
        return lock

    def load_or_seed(self, owner_guild_id: int | None = None) -> None:
        """Synchronous startup load. Must run before the bot logs in.

        `owner_guild_id` is only consulted by the v14->v15 migration, to file
        a pre-existing single-guild install's settings under the right
        `guilds[...]` entry — see bot/config.py's OWNER_GUILD_ID."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        loaded = self._try_read(self.path)
        if loaded is not None:
            self.data = loaded
            self._migrate(owner_guild_id)
            return

        if self.path.exists():
            logger.warning(strings.LOG_DATA_CORRUPT, self.path)

        loaded = self._try_read(self.backup_path)
        if loaded is not None:
            self.data = loaded
            self._migrate(owner_guild_id)
            logger.warning("Recovered data from backup file %s", self.backup_path)
            self._write_sync()
            return

        if self.backup_path.exists():
            logger.warning(strings.LOG_BACKUP_CORRUPT, self.backup_path)

        self.data = build_seed_data()
        self._write_sync()
        logger.info(strings.LOG_SEEDED_FRESH, self.path)

    @staticmethod
    def _try_read(path: Path) -> RootData | None:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return None

    def _migrate(self, owner_guild_id: int | None = None) -> None:
        version = self.data.get("version", 0)

        if version < 2:
            # v2 added a separate alert channel, falling back to the status
            # channel when unset; older files simply lack the key.
            self.data["config"].setdefault("alert_channel_id", None)
            version = 2

        if version < 3:
            # v3 added named sub-zones (scouting targets within a region).
            # Backfill the known sub-zone list for zones the guild already
            # tracks under a default key; any other (custom, admin-added)
            # zone just gets an empty sub-zone dict to fill in later via
            # /elite-config subzone-add.
            for zone_key, zone in self.data["zones"].items():
                subzones = zone.setdefault("subzones", {})
                for subzone_name in DEFAULT_SUBZONES.get(zone_key, []):
                    subzone_key = slugify(subzone_name)
                    subzones.setdefault(subzone_key, build_subzone_state(subzone_name))
            version = 3

        if version < 4:
            # v4 dropped the 7-minute spawn window: window_start becomes the
            # single spawn_at timestamp and window_end is discarded.
            for zone in self.data["zones"].values():
                zone["spawn_at"] = zone.pop("window_start", None)
                zone.pop("window_end", None)
            version = 4

        if version < 5:
            # v5 splits scouting buttons across multiple messages (one
            # button per row, max 5 rows) for zones with >5 sub-zones, so
            # each zone now tracks which message holds the shared embed.
            for zone in self.data["zones"].values():
                zone.setdefault("scouting_message", None)
            version = 5

        if version < 6:
            # v6 adds a paired "Elite Found" button per sub-zone, which must
            # disable every scouting message for the zone (not just the
            # primary one) — so scouting_message (single ref) becomes
            # scouting_messages (a list), each entry now also recording
            # which sub-zone keys it holds so a disabled view can be
            # rebuilt. Only the primary message is recoverable this way;
            # any already-sent continuation messages from before this
            # upgrade are not trackable and are left as-is.
            for zone in self.data["zones"].values():
                old_ref = zone.pop("scouting_message", None)
                if old_ref is not None:
                    chunks = chunk_subzone_keys(zone)
                    old_ref["subzone_keys"] = chunks[0] if chunks else []
                    zone["scouting_messages"] = [old_ref]
                else:
                    zone.setdefault("scouting_messages", [])
            version = 6

        if version < 7:
            # v7 replaces the separate "spawn arrived" alert message with a
            # silent edit of the existing scouting message(s), adding a
            # per-sub-zone "Elite killed" button (which also records which
            # sub-zone the kill happened in) and a found_this_cycle flag so
            # that edit doesn't clobber an already-found state.
            for zone in self.data["zones"].values():
                zone.setdefault("last_kill_subzone", None)
                zone.setdefault("found_this_cycle", False)
            version = 7

        if version < 8:
            # v8: "Elite killed" now deletes the scouting message(s) and the
            # Elite Found announcement instead of disabling their buttons,
            # posting a new "Boss killed" summary in their place — so the
            # zone now also tracks the Found announcement's own message ref
            # (previously untracked) to be able to find and delete it.
            for zone in self.data["zones"].values():
                zone.setdefault("found_announcement_message", None)
            version = 8

        if version < 9:
            # v9 renames start_alert_sent to spawn_due_marked: since v7 it no
            # longer means "an alert message was sent" (that message was
            # removed), just "the spawn-due transition has been processed
            # for this cycle" — the old name was actively misleading.
            for zone in self.data["zones"].values():
                zone["spawn_due_marked"] = zone.pop("start_alert_sent", False)
            version = 9

        if version < 10:
            # v10 corrects the dungeon sub-zone names — see the comment on
            # _V10_SUBZONE_REMOVALS above for the full story.
            for zone_key, display_name in _V10_SUBZONE_REMOVALS:
                zone = self.data["zones"].get(zone_key)
                if zone is not None:
                    zone["subzones"].pop(slugify(display_name), None)

            for zone_key, old_name, new_name in _V10_SUBZONE_RENAMES:
                zone = self.data["zones"].get(zone_key)
                if zone is None:
                    continue
                subzones = zone["subzones"]
                subzone = subzones.pop(slugify(old_name), None)
                if subzone is not None:
                    subzone["display_name"] = new_name
                    subzones[slugify(new_name)] = subzone

            for zone_key, display_name in _V10_SUBZONE_ADDITIONS:
                zone = self.data["zones"].get(zone_key)
                if zone is not None:
                    subzone_key = slugify(display_name)
                    zone["subzones"].setdefault(subzone_key, build_subzone_state(display_name))

            version = 10

        if version < 11:
            # v11 removes "syleus" as a standalone zone: it was never a real
            # region on its own — it's the boss inside Laslan Abyss (our
            # laslan-dungeon), already tracked there as the Syleus B1-B6
            # sub-zones since v10. It had no map, no sub-zones and (per
            # community reference data) no matching timer of its own, so it
            # was just dead weight left over from the original zone list.
            self.data["zones"].pop("syleus", None)
            self.data["history"].pop("syleus", None)
            self.data["undo"].pop("syleus", None)
            version = 11

        if version < 12:
            # v12 adds the mmopartybuilder.eu fallback-timer settings.
            config = self.data["config"]
            config.setdefault("fallback_enabled", False)
            config.setdefault("fallback_server", "sacred")
            config.setdefault("fallback_threshold_minutes", 5)
            version = 12

        if version < 13:
            # v13: removes "Crimson 1F" from talandre-dungeon (added
            # speculatively in case the zone ever got used, but
            # mmopartybuilder reference data confirms it never is — no
            # bundled map, no scoutable spot for it either), and corrects two
            # sub-zone names against mmopartybuilder's live data: "Quietis
            # Domain" -> "Quietis's Demesne" (its actual in-game name) and
            # "Border Zone" -> "Scar of Sacrifice" (same physical spot,
            # mmopartybuilder's name for it).
            talandre_dungeon = self.data["zones"].get("talandre-dungeon")
            if talandre_dungeon is not None:
                talandre_dungeon["subzones"].pop(slugify("Crimson 1F"), None)

            for zone_key, old_name, new_name in (
                ("talandre", "Quietis Domain", "Quietis's Demesne"),
                ("nix", "Border Zone", "Scar of Sacrifice"),
            ):
                zone = self.data["zones"].get(zone_key)
                if zone is None:
                    continue
                subzones = zone["subzones"]
                subzone = subzones.pop(slugify(old_name), None)
                if subzone is not None:
                    subzone["display_name"] = new_name
                    subzones[slugify(new_name)] = subzone

            version = 13

        if version < 14:
            # v14 adds the mmopartybuilder.eu "found" watch settings.
            config = self.data["config"]
            config.setdefault("fallback_found_watch_enabled", False)
            config.setdefault("fallback_found_watch_attempts", 10)
            config.setdefault("fallback_found_watch_slow_interval_minutes", 15)
            version = 14

        if version < 15:
            # v15: the bot became multi-guild installable — settings that
            # only make sense per-server (channel/alert-channel/alert-role/
            # admin-role/perpetual-message) move out of the single shared
            # `config` into `guilds[str(guild_id)]`, one entry per installed
            # server; `config` keeps only the truly shared settings (zones'
            # cooldowns, fallback/found-watch, offset, timezone). Likewise
            # every zone's message refs now carry which guild they belong to.
            config = self.data["config"]
            old_channel_id = config.pop("channel_id", None)
            old_alert_channel_id = config.pop("alert_channel_id", None)
            old_alert_role_id = config.pop("alert_role_id", None)
            old_admin_role_id = config.pop("admin_role_id", None)
            old_perpetual_message_id = config.pop("perpetual_message_id", None)
            guilds = self.data.setdefault("guilds", {})

            if owner_guild_id is not None:
                guild_config = guilds.setdefault(str(owner_guild_id), build_guild_config())
                guild_config["channel_id"] = old_channel_id
                guild_config["alert_channel_id"] = old_alert_channel_id
                guild_config["alert_role_id"] = old_alert_role_id
                guild_config["admin_role_id"] = old_admin_role_id
                guild_config["perpetual_message_id"] = old_perpetual_message_id

                for zone in self.data["zones"].values():
                    for ref in zone.get("scouting_messages", []):
                        ref.setdefault("guild_id", owner_guild_id)
                    old_found_ref = zone.pop("found_announcement_message", None)
                    found_refs = zone.setdefault("found_announcement_messages", [])
                    if old_found_ref is not None:
                        old_found_ref.setdefault("guild_id", owner_guild_id)
                        found_refs.append(old_found_ref)
            else:
                # No OWNER_GUILD_ID available at migration time (bot/config.py
                # always requires it in production; only reachable here from
                # code that constructs Storage directly, e.g. tests/tools).
                # A message ref with no guild_id would break every guild-
                # scoped code path downstream, so drop rather than guess —
                # same "unrecoverable, left for a fresh cycle" treatment as
                # the v6 migration gives orphaned continuation messages.
                for zone in self.data["zones"].values():
                    zone["scouting_messages"] = []
                    zone.pop("found_announcement_message", None)
                    zone["found_announcement_messages"] = []

            version = 15

        if version != SCHEMA_VERSION:
            logger.warning(
                "Data file version %s does not match expected %s after migrations; using as-is",
                version,
                SCHEMA_VERSION,
            )
        self.data["version"] = SCHEMA_VERSION

    async def save(self) -> None:
        """Persist `self.data`. Caller must already hold whichever of
        `self.lock` / `self.zone_lock(...)` guards the mutation being saved.
        The file write itself is serialized separately (it dumps the whole
        document regardless of which zone changed), so concurrent saves for
        different zones can never race on disk."""
        async with self._write_lock:
            await asyncio.to_thread(self._write_sync)

    def _write_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".elite-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if self.path.exists():
                shutil.copyfile(self.path, self.backup_path)
            os.replace(tmp_name, self.path)
        except Exception:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise
