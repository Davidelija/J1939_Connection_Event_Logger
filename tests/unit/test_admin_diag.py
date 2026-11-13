"""admin diagnostic log (LOG-20) and clock v2 (veh_time, elapsed_s)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from j1939logger.admin import DiagLog
from j1939logger.clock import Clock
from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.types import J1939Msg

START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


def make(
    tmp_path: Path, plan: Sequence[FaultSpec] = (), max_bytes: int = 10_000, files: int = 3
) -> tuple[DiagLog, Clock, FakeClock]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    p = DesktopPlatform(fault_plan=plan, clock=fc, root=tmp_path)
    clock = Clock(p, 5)
    return DiagLog(p, clock, max_bytes=max_bytes, files=files), clock, fc


def lines(diag: DiagLog) -> list[str]:
    return diag.path.read_text(encoding="utf-8").splitlines()


def test_LOG_20_one_line_per_event_with_utc_level_module_message(tmp_path: Path) -> None:
    diag, _, _ = make(tmp_path)
    diag.log("error", "capture", "can_down on vcan0 (conn 2)")
    assert lines(diag) == ["2026-11-06T14:02:11.000Z error capture can_down on vcan0 (conn 2)"]


def test_LOG_20_repeated_error_is_logged_once_with_a_count(tmp_path: Path) -> None:
    diag, _, _ = make(tmp_path)
    for _ in range(5):
        diag.log("warning", "decode", "tp_error timeout_t1")
    diag.log("info", "session", "key-off")
    assert [x.split(" ", 1)[1] for x in lines(diag)] == [
        "warning decode tp_error timeout_t1",
        "warning decode last message repeated 4 times",
        "info session key-off",
    ]


def test_LOG_20_log_is_rotated_by_size_and_file_count(tmp_path: Path) -> None:
    diag, _, _ = make(tmp_path, max_bytes=200, files=3)
    for i in range(30):
        diag.log("info", "session", f"message number {i:03d}")
    folder = diag.path.parent
    assert sorted(p.name for p in folder.iterdir()) == [
        "logger.log",
        "logger.log.1",
        "logger.log.2",
    ]
    assert all(p.stat().st_size <= 200 for p in folder.iterdir())
    assert "message number 029" in lines(diag)[-1]


def test_LOG_18_restart_cause_is_read_back_by_the_next_session(tmp_path: Path) -> None:
    diag, _, _ = make(tmp_path)
    assert diag.last_restart_cause() is None
    diag.log("info", "session", "running")
    diag.restart_cause("software restart")
    assert diag.last_restart_cause() == "software restart"
    diag.log("info", "session", "next session started")
    assert diag.last_restart_cause() is None


def test_LOG_20_without_valid_time_lines_use_seconds_since_wake(tmp_path: Path) -> None:
    diag, _, fc = make(tmp_path, [(0.0, "rtc_invalid", None)])
    fc.advance(12.5)
    diag.log("info", "session", "started")
    assert lines(diag) == ["+12.500s info session started"]


def test_LOG_20_write_failure_never_raises(tmp_path: Path) -> None:
    diag, _, _ = make(tmp_path, [(0.0, "card_removed", None)])
    diag.log("error", "eventlog", "card gone")
    assert diag.write_errors == 1


# -- clock v2 (DC-10) ------------------------------------------------------------


def td(t: datetime) -> bytes:
    return bytes([t.second * 4, t.minute, t.hour, t.month, t.day * 4, t.year - 1985, 125, 125])


def test_LOG_16_veh_time_is_none_before_time_date_then_whole_seconds(tmp_path: Path) -> None:
    _, clock, fc = make(tmp_path)
    assert clock.veh_time(100.0) is None
    vehicle = START + timedelta(seconds=1)
    clock.on_time_date(J1939Msg(100.0, 0.0, 6, 65254, 0, 255, td(vehicle), False, False, False))
    assert clock.veh_time(102.7) == vehicle + timedelta(seconds=2)


def test_LOG_16_elapsed_s_counts_from_wake(tmp_path: Path) -> None:
    _, clock, fc = make(tmp_path)
    fc.advance(3.25)
    assert clock.elapsed_s(fc.mono()) == 3.25
