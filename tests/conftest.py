"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from bot.storage import Storage
from tests.fakes import FakeBot, FakeChannel


@pytest.fixture
def storage(tmp_path):
    """A real Storage instance backed by a temp directory, freshly seeded —
    exercises the actual atomic-write/seed code path instead of a mock."""
    s = Storage(path=tmp_path / "elite.json", backup_path=tmp_path / "elite.json.bak")
    s.load_or_seed()
    return s


@pytest.fixture
def channel():
    return FakeChannel()


@pytest.fixture
def bot(storage, channel):
    return FakeBot(storage, channel)
