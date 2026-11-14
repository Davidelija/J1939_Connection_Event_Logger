"""rawcap and retention (step 6 PR 2, DC-20): raw windows, names, budget; freeing order, faults."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.rawcap import RawCap, candump_line
from j1939logger.retention import RawFile, Retention
from j1939logger.store import CardUsage
from j1939logger.types import Frame

START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
MB = 1024 * 1024
SETTINGS: dict[str, Any] = {
    "logging.raw_before_s": 10,
    "logging.raw_after_s": 60,
    "limits.raw_mb_per_session": 200,
    "storage.event_reserve_mb": 500,
    "storage.warn_pct": 90,
}
LINE = re.compile(r"^\(\d+\.\d{6}\) can0 [0-9A-F]{3}(?:[0-9A-F]{5})?#(?:[0-9A-F]*|R)$")


def frame(t: float, cid: int = 0x0CF00400, data: bytes = bytes(8), **kw: Any) -> Frame:
    return Frame(1.7e9 + t, t, cid, kw.get("extended", True), kw.get("remote", False),
                 kw.get("error", False), data, False)  # fmt: skip


def make(
    tmp_path: Path, plan: Sequence[FaultSpec] = (), over: Optional[dict[str, Any]] = None
) -> tuple[RawCap, Path]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    p = DesktopPlatform(fault_plan=plan, clock=fc, root=tmp_path)
    return RawCap(p, {**SETTINGS, **(over or {})}, 142), p.paths().card


def ring(t0: float, t1: float, step: float = 0.5) -> list[Frame]:
    out, t = [], t0
    while t <= t1:
        out.append(frame(t))
        t += step
    return out


# -- LOG-10: raw captures ----------------------------------------------------------


def test_LOG_10_window_runs_from_10_s_before_to_60_s_after_the_event(tmp_path: Path) -> None:
    rc, card = make(tmp_path)
    name = rc.start(2, 200.0, ring(185.0, 200.0))  # the ring holds more than 10 s
    assert name == "raw/s000142_c2_e1.log"
    rc.feed(ring(200.5, 275.0))
    assert rc.poll(259.0) == [] and rc.open_captures == 1
    assert rc.poll(261.0) == [name]
    lines = (card / name).read_text("ascii").splitlines()
    times = [float(x[1:18]) - 1.7e9 for x in lines]
    assert min(times) >= 190.0 - 1e-6 and max(times) <= 260.0 + 1e-6
    assert min(times) <= 200.0 <= max(times)  # the window contains the event's time
    assert all(LINE.match(x) for x in lines)


def test_LOG_10_names_count_each_connections_captures(tmp_path: Path) -> None:
    rc, _ = make(tmp_path)
    assert rc.start(2, 100.0, []) == "raw/s000142_c2_e1.log"  # connection start
    assert rc.start(2, 130.0, []) == "raw/s000142_c2_e2.log"  # its control flag
    assert rc.start(3, 131.0, []) == "raw/s000142_c3_e1.log"


def test_LOG_10_candump_format_for_extended_standard_remote_and_error_frames() -> None:
    assert candump_line(frame(0.118204, 0x18EEFFF9, bytes.fromhex("C4B2A13300810080"))) == (
        "(1700000000.118204) can0 18EEFFF9#C4B2A13300810080\n"
    )
    assert candump_line(frame(0.0, 0x123, b"\x01", extended=False)) == (
        "(1700000000.000000) can0 123#01\n"
    )
    assert candump_line(frame(0.0, 0x123, b"", extended=False, remote=True)).endswith("123#R\n")
    assert candump_line(frame(0.0, 0x40, bytes(8), extended=False, error=True)).startswith(
        "(1700000000.000000) can0 20000040#"
    )


def test_LOG_10_open_captures_are_written_at_session_end(tmp_path: Path) -> None:
    rc, card = make(tmp_path)
    name = rc.start(2, 100.0, ring(95.0, 100.0))
    rc.feed(ring(100.5, 110.0))
    assert rc.close() == [name]
    assert len((card / str(name)).read_text("ascii").splitlines()) == 31


def test_LOG_10_no_capture_once_the_session_budget_is_used(tmp_path: Path) -> None:
    rc, _ = make(tmp_path, over={"limits.raw_mb_per_session": 0.0001})  # about 100 bytes
    first = rc.start(2, 100.0, ring(95.0, 100.0))
    rc.close()
    assert first is not None and rc.bytes_written > 100
    assert rc.start(3, 200.0, []) is None  # raw_capture is then null (DC-14)


def test_LOG_22_no_capture_once_only_the_reserve_is_left(tmp_path: Path) -> None:
    rc, _ = make(tmp_path)
    rc.stop("card full")
    assert rc.start(2, 100.0, []) is None


def test_LOG_22_write_error_is_a_high_fault_not_an_exception(tmp_path: Path) -> None:
    rc, card = make(tmp_path, [(0.0, "enospc", None)])
    name = rc.start(2, 100.0, ring(95.0, 100.0))
    assert rc.close() == []
    [fault] = rc.take_faults()
    assert fault.sev == "high" and "enospc" in fault.fields["cause"]
    assert not (card / str(name)).exists()


# -- LOG-11, LOG-22: retention ------------------------------------------------------


def usage(free_mb: float, total_mb: float = 8000) -> CardUsage:
    total = int(total_mb * MB)
    free = int(free_mb * MB)
    return CardUsage(total, total - free, free)


def raw(name: str, mtime: float, size_mb: float, retrieved: bool = False) -> RawFile:
    return RawFile(Path("raw") / name, mtime, int(size_mb * MB), retrieved)


def test_LOG_11_nothing_is_freed_while_there_is_room() -> None:
    plan = Retention(SETTINGS).check(usage(2000), [raw("a.log", 1, 50, True)])
    assert (plan.free, plan.faults, plan.raw_allowed) == ([], [], True)


def test_LOG_11_retrieved_captures_go_first_then_unretrieved_oldest_first() -> None:
    files = [raw("new.log", 30, 40), raw("old.log", 10, 40), raw("got_new.log", 20, 40, True),
             raw("got_old.log", 5, 40, True)]  # fmt: skip
    plan = Retention(SETTINGS).check(usage(600), files)  # 100 MB short of 700
    assert [p.name for p in plan.free] == ["got_old.log", "got_new.log", "old.log"]
    plan2 = Retention(SETTINGS).check(usage(690), files)
    assert [p.name for p in plan2.free] == ["got_old.log"]


def test_LOG_11_only_raw_captures_are_ever_listed() -> None:
    plan = Retention(SETTINGS).check(usage(10), [raw("a.log", 1, 1)])
    assert all(p.parts[0] == "raw" for p in plan.free)


def test_LOG_22_notice_at_warn_pct_once_per_session() -> None:
    r = Retention(SETTINGS)
    first = r.check(usage(790), [])  # 90.1% used, but room above the reserve and budget
    assert [(f.sev, f.fields["cause"]) for f in first.faults] == [
        ("notice", "card nearly full (90.1% used)"),
    ]
    assert r.check(usage(790), []).faults == []


def test_LOG_22_only_the_reserve_left_stops_raw_captures_with_a_high_fault() -> None:
    r = Retention(SETTINGS)
    plan = r.check(usage(450), [raw("a.log", 1, 10)])
    assert not plan.raw_allowed
    assert [f.fields["cause"] for f in plan.faults if f.sev == "high"] == [
        "card full; raw captures stopped"
    ]
    assert [f.sev for f in r.check(usage(450), []).faults] == []  # once per session
