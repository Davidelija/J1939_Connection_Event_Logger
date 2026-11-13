"""FakeClock (docs/modules.md section 5, injection points): advance and jump."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from j1939logger.platform.desktop import FakeClock

START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


def test_LOG_16_fakeclock_starts_at_given_times() -> None:
    clock = FakeClock(start_utc=START, start_mono=50.0)
    assert clock.mono() == 50.0
    assert clock.wall() == START


def test_LOG_16_fakeclock_default_start_is_utc_and_positive_mono() -> None:
    clock = FakeClock()
    assert clock.wall().tzinfo is not None
    assert clock.wall().utcoffset() == timedelta(0)
    assert clock.mono() > 0


def test_LOG_16_fakeclock_advance_moves_mono_and_wall_together() -> None:
    clock = FakeClock(start_utc=START, start_mono=0.0)
    clock.advance(60.0)
    clock.advance(0.25)
    assert clock.mono() == pytest.approx(60.25)
    assert clock.wall() == START + timedelta(seconds=60.25)


def test_LOG_16_fakeclock_runs_24_hours_in_one_call() -> None:
    clock = FakeClock(start_utc=START, start_mono=0.0)
    clock.advance(24 * 3600)
    assert clock.mono() == 24 * 3600
    assert clock.wall() == START + timedelta(hours=24)


def test_LOG_16_fakeclock_jump_moves_wall_only_so_timers_do_not_move() -> None:
    clock = FakeClock(start_utc=START, start_mono=10.0)
    clock.jump(3600.0)
    assert clock.mono() == 10.0
    assert clock.wall() == START + timedelta(hours=1)
    clock.jump(-7200.0)
    assert clock.mono() == 10.0
    assert clock.wall() == START - timedelta(hours=1)


def test_LOG_16_fakeclock_advance_never_goes_back() -> None:
    clock = FakeClock()
    with pytest.raises(ValueError):
        clock.advance(-1.0)


def test_LOG_16_fakeclock_rejects_naive_start() -> None:
    with pytest.raises(ValueError):
        FakeClock(start_utc=datetime(2026, 11, 6, 14, 2, 11))
