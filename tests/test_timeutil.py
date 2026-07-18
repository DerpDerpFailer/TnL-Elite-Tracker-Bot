from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from bot.timeutil import get_zoneinfo, parse_duration_to_minutes, parse_zone_datetime, to_epoch


class TestParseDurationToMinutes:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("4h", 240),
            ("5h30", 330),
            ("5h30m", 330),
            ("90m", 90),
            ("90", 90),
            ("1h", 60),
            (" 4h ", 240),
            ("4H", 240),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_duration_to_minutes(raw) == expected

    @pytest.mark.parametrize("raw", ["", "bogus", "h30", "-4h", "0h", "0m", "0"])
    def test_invalid(self, raw):
        with pytest.raises(ValueError):
            parse_duration_to_minutes(raw)


class TestParseZoneDatetime:
    tz = ZoneInfo("Europe/Paris")

    def test_none_returns_now(self):
        now = datetime(2026, 7, 18, 15, 0, tzinfo=self.tz)
        assert parse_zone_datetime(None, self.tz, now) == now

    def test_blank_returns_now(self):
        now = datetime(2026, 7, 18, 15, 0, tzinfo=self.tz)
        assert parse_zone_datetime("   ", self.tz, now) == now

    def test_hhmm_today(self):
        now = datetime(2026, 7, 18, 15, 0, tzinfo=self.tz)
        result = parse_zone_datetime("14:30", self.tz, now)
        assert result == datetime(2026, 7, 18, 14, 30, tzinfo=self.tz)

    def test_hhmm_future_rolls_back_a_day(self):
        # reporting a kill from just before midnight, just after midnight now
        now = datetime(2026, 7, 18, 0, 5, tzinfo=self.tz)
        result = parse_zone_datetime("23:50", self.tz, now)
        assert result == datetime(2026, 7, 17, 23, 50, tzinfo=self.tz)

    def test_ddmm_hhmm(self):
        now = datetime(2026, 7, 18, 15, 0, tzinfo=self.tz)
        result = parse_zone_datetime("14/07 09:10", self.tz, now)
        assert result == datetime(2026, 7, 14, 9, 10, tzinfo=self.tz)

    def test_ddmm_future_rolls_back_a_year(self):
        now = datetime(2026, 1, 2, 10, 0, tzinfo=self.tz)
        result = parse_zone_datetime("31/12 23:00", self.tz, now)
        assert result == datetime(2025, 12, 31, 23, 0, tzinfo=self.tz)

    def test_invalid_raises(self):
        now = datetime(2026, 7, 18, 15, 0, tzinfo=self.tz)
        with pytest.raises(ValueError):
            parse_zone_datetime("not a time", self.tz, now)


def test_get_zoneinfo_valid():
    assert get_zoneinfo("Europe/Paris").key == "Europe/Paris"


def test_get_zoneinfo_invalid():
    with pytest.raises(ZoneInfoNotFoundError):
        get_zoneinfo("Not/AZone")


def test_to_epoch_matches_timestamp():
    dt = datetime(2026, 1, 1, 12, 30, 45, tzinfo=ZoneInfo("UTC"))
    assert to_epoch(dt) == int(dt.timestamp())
