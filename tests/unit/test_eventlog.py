"""eventlog (append only): hash rule, key order, one write per record, storage faults."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from j1939logger.clock import Clock
from j1939logger.eventlog import ZERO_HASH, EventLog, format_utc, format_veh_time, record_hash
from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.types import Record

START = datetime(2026, 11, 6, 14, 2, 11, 402000, tzinfo=timezone.utc)
EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/s000142_20261106T140211Z.jsonl"


def setup(tmp_path: Path, plan: Sequence[FaultSpec] = ()) -> tuple[EventLog, FakeClock, Path]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    p = DesktopPlatform(fault_plan=plan, clock=fc, root=tmp_path)
    clock = Clock(p, 5)
    path = p.paths().card / "s000142_20261106T140211Z.jsonl"
    return EventLog(p, clock, path, session=142, prev=ZERO_HASH), fc, path


def conn_start(utc: datetime) -> Record:
    return Record(
        type="connection_start",
        sev="high",
        utc=utc,
        veh_time=None,
        fields={"sa": 249, "name": "0x8000810033A1B2C4", "trigger": "new address claim"},
        conn=2,
    )


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def verify(recs: list[dict[str, Any]], first_prev: str) -> None:
    prev = first_prev
    for r in recs:
        body = {k: v for k, v in r.items() if k != "hash"}
        assert r["prev"] == prev
        assert record_hash(prev, body) == r["hash"]
        prev = r["hash"]


def test_LOG_5_hash_rule_reproduces_every_session_142_hash() -> None:
    recs = [json.loads(x) for x in EXAMPLE.read_text(encoding="utf-8").splitlines()]
    verify(recs, recs[0]["prev"])


def test_LOG_5_appended_records_form_a_chain_from_prev(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path)
    log.append(conn_start(START))
    fc.advance(1.0)
    log.append(Record("time_sync", "info", START, None, {"source_sa": 0, "offset_s": 0.05}))
    recs = lines(path)
    verify(recs, ZERO_HASH)
    assert log.last_hash == recs[-1]["hash"]
    assert [r["rec"] for r in recs] == [1, 2]


def test_LOG_4_fields_and_key_order_match_the_log_format(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path)
    fc.advance(0.04)
    event_id = log.append(conn_start(START))
    r = lines(path)[0]
    assert list(r) == [
        "rec", "type", "sev", "utc", "written", "veh_time", "conn", "sa", "name", "trigger",
        "clock_valid", "clock_source", "prev", "hash",
    ]  # fmt: skip
    assert r["utc"] == "2026-11-06T14:02:11.402Z"
    assert r["written"] == "2026-11-06T14:02:11.442Z"
    assert (r["clock_valid"], r["clock_source"], r["veh_time"]) == (True, "rtc", None)
    assert event_id == "142-1"


def test_LOG_4_time_formats() -> None:
    t = datetime(2026, 11, 6, 14, 2, 12, 951999, tzinfo=timezone.utc)
    assert format_utc(t) == "2026-11-06T14:02:12.951Z"
    assert format_veh_time(t) == "2026-11-06T14:02:12Z"
    assert format_utc(None) is None


def test_LOG_4_eventlog_owned_fields_cannot_be_overridden(tmp_path: Path) -> None:
    log, _, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        log.append(Record("fault", "high", START, None, {"hash": "x"}))


def test_LOG_3_one_write_per_record_to_an_append_only_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, _, path = setup(tmp_path)
    flags: list[int] = []
    writes: list[int] = []
    real_open, real_write = os.open, os.write

    def spy_open(p: Any, f: int, *a: Any) -> int:
        flags.append(f)
        return real_open(p, f, *a)

    def spy_write(fd: int, data: bytes) -> int:
        writes.append(len(data))
        return real_write(fd, data)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "write", spy_write)
    for i in range(3):
        log.append(conn_start(START + timedelta(seconds=i)))
    assert len(writes) == 3
    assert flags and all(f & os.O_APPEND for f in flags)
    assert path.read_bytes().count(b"\n") == 3


def test_LOG_3_sync_now_syncs_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log, _, _ = setup(tmp_path)
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    assert log.sync_now() is True  # nothing open yet
    log.append(conn_start(START))
    assert log.sync_now() is True
    assert len(synced) == 1


def test_LOG_22_storage_error_gives_high_fault_and_keeps_the_chain(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path, [(101.0, "enospc", {"for_s": 1.0})])
    log.append(conn_start(START))
    fc.advance(1.0)
    assert log.append(conn_start(START)) is None  # card full: not written
    faults = log.take_faults()
    assert [(f.type, f.sev) for f in faults] == [("fault", "high")]
    assert "enospc" in faults[0].fields["cause"]
    fc.advance(1.0)
    assert log.append(conn_start(START)) == "142-2"  # chain continues where it stopped
    verify(lines(path), ZERO_HASH)


def test_LOG_22_repeated_storage_error_is_one_fault_with_a_count(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path, [(101.0, "eio", {"ops": ["card_write"], "for_s": 2.0})])
    log.append(conn_start(START))
    fc.advance(1.0)  # the card fails writes for 2 s
    for _ in range(3):
        assert log.append(conn_start(START)) is None  # three records lost
    [fault] = log.take_faults()  # one fault for the outage, not three (CLAUDE.md rule 14)
    assert log.append(fault) is None  # the fault itself cannot be written yet ...
    [again] = log.take_faults()
    assert again is fault  # ... so the same record is handed out again, not a new one
    fc.advance(2.0)  # the card is back
    assert log.append(fault) is not None
    assert log.take_faults() == []
    written = lines(path)[-1]
    assert (written["type"], written["sev"], written["cause"]) == (
        "fault",
        "high",
        "storage error (eio)",
    )
    assert written["logger_action"] == "3 records not written; recording continues"
    verify(lines(path), ZERO_HASH)


def test_LOG_22_a_single_storage_error_says_record_not_written(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path, [(101.0, "enospc", {"for_s": 1.0})])
    log.append(conn_start(START))
    fc.advance(1.0)
    assert log.append(conn_start(START)) is None
    [fault] = log.take_faults()
    fc.advance(1.0)
    assert log.append(fault) is not None
    assert lines(path)[-1]["logger_action"] == "record not written"


SYNC_FAILED = "sync failed; records since the last sync may not be on the card"  # QC-4 E2


def _storage_faults(path: Path) -> list[dict[str, Any]]:
    return [r for r in lines(path) if r["type"] == "fault" and r["cause"].startswith("storage")]


def test_LOG_22_sync_thread_fault_is_never_lost(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path, [
        (101.0, "eio", {"ops": ["card_sync"], "for_s": 1.0}),  # the sync thread fails
        (103.0, "eio", {"ops": ["card_write"], "for_s": 1.0}),  # then a write fails
        (110.0, "eio", {"ops": ["card_write"], "for_s": 1.0}),  # a later, separate outage
    ])  # fmt: skip
    log.append(conn_start(START))
    fc.advance(1.0)  # 101: syncs fail
    log.start_sync(0.001)
    taken: list[Record] = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and (not taken or time.monotonic() < deadline - 4.8):
        taken += log.take_faults()  # the session takes faults while the sync thread fails
    assert len(taken) == 1  # one outage, one fault, however many syncs failed
    [fault] = taken
    assert fault.fields["logger_action"] == SYNC_FAILED
    fc.advance(2.0)  # 103: syncs work again, writes fail
    assert log.append(conn_start(START)) is None  # a record lost in the same outage
    assert log.append(fault) is None  # the fault cannot be written yet ...
    assert log.take_faults() == [fault]  # ... and is handed out again, never dropped
    fc.advance(2.0)  # 105: the card is back
    assert log.append(fault) is not None
    [written] = _storage_faults(path)  # exactly one storage fault record for the outage
    assert written["logger_action"] == "record not written"  # one record was lost
    fc.advance(5.0)  # 110: a later outage
    assert log.append(conn_start(START)) is None
    [later] = log.take_faults()
    assert later is not fault  # a new outage is reported again
    fc.advance(2.0)
    assert log.append(later) is not None
    log.stop_sync()
    assert len(_storage_faults(path)) == 2
    verify(lines(path), ZERO_HASH)


def test_LOG_22_sync_failure_with_no_record_lost_says_sync_failed(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path, [(101.0, "eio", {"ops": ["card_sync"], "for_s": 1.0})])
    log.append(conn_start(START))
    fc.advance(1.0)
    assert log.sync_now() is False
    [fault] = log.take_faults()
    fc.advance(1.0)
    assert log.append(fault) is not None
    [written] = _storage_faults(path)
    assert written["logger_action"] == SYNC_FAILED


def test_LOG_22_card_removed_then_reinserted_reopens_the_file(tmp_path: Path) -> None:
    log, fc, path = setup(tmp_path, [(101.0, "card_removed", {"for_s": 1.0})])
    log.append(conn_start(START))
    fc.advance(1.0)
    assert log.sync_now() is False
    assert [f.type for f in log.take_faults()] == ["fault"]
    fc.advance(1.0)
    assert log.append(conn_start(START)) == "142-2"
    verify(lines(path), ZERO_HASH)


def test_LOG_22_slow_sync_delays_but_succeeds(tmp_path: Path) -> None:
    log, fc, _ = setup(tmp_path, [(100.0, "slow_sync", {"s": 3.0, "for_s": 1.0})])
    log.append(conn_start(START))
    assert log.sync_now() is True
    assert fc.mono() == pytest.approx(103.0)
    assert log.take_faults() == []
