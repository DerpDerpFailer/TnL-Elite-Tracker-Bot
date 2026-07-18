"""Atomic, single-file JSON persistence for /data/elite.json.

Writes never touch the destination path directly: data is written to a
temp file in the same directory, fsynced, and swapped in with os.replace so a
crash mid-write can never leave a truncated/corrupt elite.json. The previous
version is copied to elite.json.bak before each swap.

`Storage.lock` is a single asyncio.Lock shared by every command and background
task that mutates `Storage.data`; callers acquire it, mutate `self.data`, then
call `await storage.save()` (which does not itself acquire the lock).
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
from bot.models import RootData, build_seed_data, build_subzone_state
from bot.scouting import chunk_subzone_keys
from bot.slugs import slugify

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, path: Path = DATA_FILE, backup_path: Path = BACKUP_FILE) -> None:
        self.path = path
        self.backup_path = backup_path
        self.lock = asyncio.Lock()
        self.data: RootData = build_seed_data()

    def load_or_seed(self) -> None:
        """Synchronous startup load. Must run before the bot logs in."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        loaded = self._try_read(self.path)
        if loaded is not None:
            self.data = loaded
            self._migrate()
            return

        if self.path.exists():
            logger.warning(strings.LOG_DATA_CORRUPT, self.path)

        loaded = self._try_read(self.backup_path)
        if loaded is not None:
            self.data = loaded
            self._migrate()
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

    def _migrate(self) -> None:
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

        if version != SCHEMA_VERSION:
            logger.warning(
                "Data file version %s does not match expected %s after migrations; using as-is",
                version,
                SCHEMA_VERSION,
            )
        self.data["version"] = SCHEMA_VERSION

    async def save(self) -> None:
        """Persist `self.data`. Caller must already hold `self.lock`."""
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
