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
from bot.constants import BACKUP_FILE, DATA_FILE, MAPS_DIR, SCHEMA_VERSION
from bot.models import RootData, build_seed_data

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
        MAPS_DIR.mkdir(parents=True, exist_ok=True)

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
