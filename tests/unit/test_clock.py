"""clock: source choice, to_utc, Time/Date, skew fault, jumps."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from j1939logger.clock import Clock, parse_time_date
from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.types import J1939Msg

START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


def setup(tmp_path: Path, plan: Sequence[FaultSpec] = ()) -> tuple[Clock, FakeClock]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    return Clock(DesktopPlatform(fault_plan=plan, clock=fc, root=tmp_path), 5), fc


def td_bytes(t: datetime) -> bytes:
    return bytes([t.second * 4, t.minute, t.hour, t.month, t.day * 4, t.year - 1985, 125, 125])


def td_msg(t: datetime, ts_mono: float, sa: int = 0) -> J1939Msg:
    return J1939Msg(ts_mono, 0.0, 6, 65254, sa, 255, td_bytes(t), False, False, False)


def test_LOG_16_parse_time_date() -> None:
    t = datetime(2026, 11, 6, 14, 2, 12, tzinfo=timezone.utc)
    assert parse_time_date(td_bytes(t)) == t
    assert parse_time_date(b"\xff" * 8) is None  # not available
    assert parse_time_date(bytes(5)) is None


def test_LOG_16_rtc_source_when_rtc_valid(tmp_path: Path) -> None:
    clock, fc = setup(tmp_path)
    r = clock.now()
    assert (r.source, r.valid, r.wall_utc) == ("rtc", True, START)
    assert clock.to_utc(99.5) == START - timedelta(seconds=0.5)


def test_LOG_16_elapsed_source_without_rtc_or_vehicle_time(tmp_path: Path) -> None:
    clock, _ = setup(tmp_path, [(0.0, "rtc_invalid", None)])
    r = clock.now()
    assert (r.source, r.valid, r.wall_utc) == ("elapsed", False, None)
    assert clock.to_utc(100.0) is None


def test_LOG_16_never_waits_for_the_clock_with_rtc_invalid(tmp_path: Path) -> None:
    # Starting with an invalid RTC returns at once with source "elapsed".
    clock, fc = setup(tmp_path, [(0.0, "rtc_invalid", None)])
    assert clock.now().source == "elapsed"
    assert fc.mono() == 100.0


def test_LOG_16_vehicle_time_kept_as_offset_when_rtc_invalid(tmp_path: Path) -> None:
    clock, fc = setup(tmp_path, [(0.0, "rtc_invalid", None)])
    vehicle = datetime(2026, 11, 6, 14, 0, 0, tzinfo=timezone.utc)
    recs = clock.on_time_date(td_msg(vehicle, ts_mono=100.0, sa=0))
    assert [r.type for r in recs] == ["time_sync"]
    assert recs[0].fields == {"source_sa": 0, "offset_s": None}
    fc.advance(10.0)
    r = clock.now()
    assert (r.source, r.valid) == ("vehicle", False)
    assert r.wall_utc == vehicle + timedelta(seconds=10)
    assert clock.to_utc(105.0) == vehicle + timedelta(seconds=5)


def test_LOG_16_first_time_date_gives_time_sync_with_offset(tmp_path: Path) -> None:
    clock, _ = setup(tmp_path)
    recs = clock.on_time_date(td_msg(START + timedelta(seconds=1), ts_mono=100.0))
    assert [r.type for r in recs] == ["time_sync"]
    assert recs[0].fields["offset_s"] == pytest.approx(1.0)
    assert recs[0].sev == "info"
    assert clock.on_time_date(td_msg(START, ts_mono=100.0)) == []  # only the first


def test_LOG_16_skew_over_limit_is_notice_fault_and_rtc_kept(tmp_path: Path) -> None:
    clock, _ = setup(tmp_path)
    recs = clock.on_time_date(td_msg(START + timedelta(minutes=6), ts_mono=100.0))
    assert [(r.type, r.sev) for r in recs] == [("time_sync", "info"), ("fault", "notice")]
    assert clock.now().source == "rtc"
    assert clock.now().wall_utc == START


def test_LOG_16_clock_jump_does_not_move_monotonic_timers(tmp_path: Path) -> None:
    clock, fc = setup(tmp_path)
    fc.jump(3600)
    assert clock.mono() == 100.0
    fc.advance(1.0)
    assert clock.mono() == 101.0


def test_LOG_16_own_and_other_pgns_ignored(tmp_path: Path) -> None:
    clock, _ = setup(tmp_path)
    own = J1939Msg(100.0, 0.0, 6, 65254, 247, 255, td_bytes(START), False, True, False)
    other = J1939Msg(100.0, 0.0, 6, 61444, 0, 255, bytes(8), False, False, False)
    assert clock.on_time_date(own) == [] and clock.on_time_date(other) == []
