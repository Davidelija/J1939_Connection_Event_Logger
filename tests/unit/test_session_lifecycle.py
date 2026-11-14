"""session lifecycle (step 2): header, end, numbering, previous end, key-off, roll-over."""

from __future__ import annotations

import json
import os
import socket
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

import pytest

from j1939logger.eventlog import ZERO_HASH, record_hash
from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.session import Session, session_files, settings_from_config
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


class _IdleSocket:
    def setsockopt(self, *a: Any) -> None: ...
    def getsockopt(self, *a: Any) -> int:
        return 1 << 21

    def settimeout(self, t: float) -> None: ...
    def recvmsg(self, *a: Any) -> Any:
        time.sleep(0.005)  # like a real socket timeout, without spinning the CPU
        raise socket.timeout()

    def send(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None: ...


class _NoBus(DesktopPlatform):
    def open_can(self, listen_only: bool) -> socket.socket:
        return cast(socket.socket, _IdleSocket())


def settings(**overrides: Any) -> dict[str, Any]:
    s = settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))
    s.update(overrides)
    return s


def make(
    root: Path,
    plan: Sequence[FaultSpec] = (),
    fc: Optional[FakeClock] = None,
    startup_faults: Optional[list[str]] = None,
    overrides: Optional[dict[str, Any]] = None,
) -> tuple[Session, FakeClock, _NoBus]:
    fc = fc or FakeClock(start_utc=START, start_mono=100.0)
    p = _NoBus(fault_plan=plan, clock=fc, root=root)
    versions = {"config": "cfg-v3", "inventory": "inv-v2", "library": "lib-v1"}
    return Session(p, settings(**(overrides or {})), None, versions, startup_faults), fc, p


def eec1(t: float) -> Frame:
    return Frame(t + 1.7e9, t, 0x0CF00400, True, False, False, bytes(8), False)


def feed(s: Session, fc: FakeClock, seconds: float, every: float = 1.0) -> None:
    end = fc.mono() + seconds
    while fc.mono() < end:
        s.capture._ingest(eec1(fc.mono()))
        s.step()
        fc.advance(every)


def recs(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def all_records(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in session_files(root / "card" / "sessions"):
        out += recs(f.path)
    return out


def verify(records: list[dict[str, Any]], first_prev: str = ZERO_HASH) -> None:
    prev = first_prev
    for r in records:
        assert r["prev"] == prev, r["rec"]
        assert record_hash(prev, {k: v for k, v in r.items() if k != "hash"}) == r["hash"]
        prev = r["hash"]


def state(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / "flash" / "state.json").read_text("utf-8"))
    return data


def stop(s: Session) -> None:
    s.stop()
    s.run()


def test_LOG_6_session_start_header_has_every_field(tmp_path: Path) -> None:
    s, _, _ = make(tmp_path)
    s.start()
    stop(s)
    first = all_records(tmp_path)[0]
    assert first["type"] == "session_start" and first["rec"] == 1
    for key in (
        "format", "session", "part", "sw", "config", "inventory", "library", "vin", "vin_status",
        "wake", "ready_s", "bitrate", "bitrate_check", "rx_buffer_actual_bytes", "connector",
        "network", "prev_session", "prev_session_end", "prev_end_cause", "bytes_cut_off",
        "logger_sa", "logger_name", "logger_claim", "new_card", "restart_guard",
        "operator_keys", "untrained", "raw_dir",
    ):  # fmt: skip
        assert key in first, key
    assert (first["format"], first["session"], first["part"]) == ("log-1", 1, 1)
    assert (first["config"], first["vin_status"], first["wake"]) == (
        "cfg-v3",
        "pending",
        "power-on",
    )
    assert first["logger_name"] == "0x9FFEFFFFFFE00001" and first["connector"] == "9-pin black"
    assert first["untrained"] is True and first["new_card"] is False
    assert first["prev"] == ZERO_HASH  # a new logger


def test_LOG_15_header_and_end_carry_buffer_size_and_kernel_drops(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    s.capture._ingest(eec1(fc.mono()), drops=4)
    s.step()
    stop(s)
    r = all_records(tmp_path)
    assert r[0]["rx_buffer_actual_bytes"] == 1 << 21
    assert r[-1]["type"] == "session_end" and r[-1]["kernel_drops"] == 4
    assert r[-1]["frames_not_j1939"] == {"std_11bit": 0, "remote": 0, "error": 0}


def test_LOG_5_state_json_written_at_start_and_end(tmp_path: Path) -> None:
    s, _, _ = make(tmp_path)
    s.start()
    st = state(tmp_path)
    assert (st["format"], st["session"], st["logger_id"]) == ("state-1", 1, "0x9FFEFFFFFFE00001")
    stop(s)
    assert state(tmp_path)["last_hash"] == all_records(tmp_path)[-1]["hash"]


def test_LOG_17_key_off_after_30_s_silence_then_new_session_on_next_frame(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    feed(s, fc, 5)
    fc.advance(31)
    s.step()
    assert not s.open
    end = all_records(tmp_path)[-1]
    assert (end["type"], end["reason"]) == ("session_end", "key-off, bus silent")
    s.capture._ingest(eec1(fc.mono()))
    s.step()
    stop(s)
    files = session_files(tmp_path / "card" / "sessions")
    assert [f.session for f in files] == [1, 2]
    second = recs(files[1].path)[0]
    assert (second["wake"], second["prev_session"], second["prev_session_end"]) == (
        "CAN activity",
        1,
        "clean",
    )
    verify(all_records(tmp_path))  # one chain across both sessions


def test_LOG_12_clean_end_is_recognized_at_next_start(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    stop(s)
    s2, _, _ = make(tmp_path, fc=fc)
    s2.start()
    stop(s2)
    first2 = recs(session_files(tmp_path / "card" / "sessions")[1].path)[0]
    assert (first2["session"], first2["prev_session_end"], first2["bytes_cut_off"]) == (
        2,
        "clean",
        0,
    )
    verify(all_records(tmp_path))


def test_LOG_12_power_loss_reports_bytes_cut_off_and_chain_continues(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    feed(s, fc, 2)
    s.capture.stop()  # power lost: no session_end
    assert s.eventlog is not None
    path = s.eventlog.path
    s.eventlog.close()
    with open(path, "ab") as f:
        f.write(b'{"rec":9,"type":"conn')  # incomplete last line, never rewritten
    s2, _, _ = make(tmp_path, fc=fc)
    s2.start()
    stop(s2)
    first2 = recs(session_files(tmp_path / "card" / "sessions")[1].path)[0]
    assert first2["prev_session_end"] == "power loss"
    assert first2["bytes_cut_off"] == len(b'{"rec":9,"type":"conn')
    complete = [json.loads(x) for x in path.read_bytes().split(b"\n")[:-1]]
    assert first2["prev"] == complete[-1]["hash"]


def test_LOG_18_software_restart_cause_from_the_diagnostic_log(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    feed(s, fc, 2)  # the header is written once the claim settles
    s.diag.restart_cause("software restart")
    s.capture.stop()
    assert s.eventlog is not None
    s.eventlog.close()
    s2, _, _ = make(tmp_path, fc=fc)
    s2.start()
    stop(s2)
    first2 = recs(session_files(tmp_path / "card" / "sessions")[1].path)[0]
    assert (first2["prev_session_end"], first2["prev_end_cause"]) == (
        "software restart",
        "software restart",
    )


def test_LOG_5_numbering_uses_the_higher_of_state_json_and_the_card(tmp_path: Path) -> None:
    s, fc, p = make(tmp_path)
    s.start()
    stop(s)
    st = state(tmp_path)
    st["session"] = 41
    (tmp_path / "flash" / "state.json").write_text(json.dumps(st))
    s2, _, _ = make(tmp_path, fc=fc)
    s2.start()
    stop(s2)
    assert [f.session for f in session_files(tmp_path / "card" / "sessions")] == [1, 42]


def test_LOG_5_blank_card_with_state_file_is_a_new_card(tmp_path: Path) -> None:
    (tmp_path / "flash").mkdir()
    (tmp_path / "flash" / "state.json").write_text(
        json.dumps(
            {
                "format": "state-1",
                "logger_id": "0x9FFEFFFFFFE00001",
                "session": 141,
                "last_hash": "a" * 64,
            }
        )
    )
    s, _, _ = make(tmp_path)
    s.start()
    stop(s)
    first = all_records(tmp_path)[0]
    assert (first["session"], first["new_card"], first["prev"]) == (142, True, ZERO_HASH)


def test_LOG_5_corrupt_state_with_sessions_continues_from_the_card(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    stop(s)
    (tmp_path / "flash" / "state.json").write_text("{not json")
    s2, _, _ = make(tmp_path, fc=fc)
    s2.start()
    stop(s2)
    second = recs(session_files(tmp_path / "card" / "sessions")[1].path)
    assert second[0]["session"] == 2
    assert [(r["type"], r["sev"]) for r in second[1:2]] == [("fault", "notice")]
    verify(all_records(tmp_path))


def test_LOG_2_roll_over_continues_rec_and_chain_in_part_2(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path, overrides={"logging.session_rollover_h": 0.01})  # 36 s
    s.start()
    feed(s, fc, 40)
    stop(s)
    files = session_files(tmp_path / "card" / "sessions")
    assert [(f.session, f.part) for f in files] == [(1, 1), (1, 2)]
    p1, p2 = recs(files[0].path), recs(files[1].path)
    assert (p1[-1]["type"], p1[-1]["reason"]) == ("session_end", "session roll-over")
    assert (p2[0]["type"], p2[0]["part"], p2[0]["session"]) == ("session_start", 2, 1)
    assert p2[0]["rec"] == p1[-1]["rec"] + 1  # DC-11
    assert files[1].path.name.endswith("_p2.jsonl")
    verify(p1 + p2)


def test_LOG_16_without_valid_time_file_is_noclock_and_records_carry_elapsed_s(
    tmp_path: Path,
) -> None:
    s, fc, _ = make(tmp_path, plan=[(0.0, "rtc_invalid", None)])
    s.start()
    fc.advance(2.5)
    stop(s)
    [f] = session_files(tmp_path / "card" / "sessions")
    assert f.path.name == "s000001_noclock.jsonl"
    for r in recs(f.path):
        assert r["utc"] is None and r["written"] is None and r["clock_source"] == "elapsed"
        assert isinstance(r["elapsed_s"], float)
    assert recs(f.path)[-1]["elapsed_s"] == 2.5


def test_STS_18_watchdog_is_kicked_on_every_loop(tmp_path: Path) -> None:
    s, fc, p = make(tmp_path)
    s.start()
    before = p.watchdog_kicks
    feed(s, fc, 5)
    assert p.watchdog_kicks - before == 5
    stop(s)


def test_STS_19_corrupt_inventory_runs_untrained_with_high_fault(tmp_path: Path) -> None:
    s, _, _ = make(tmp_path, startup_faults=["inventory corrupt (bad NAME); running untrained"])
    s.start()
    stop(s)
    r = all_records(tmp_path)
    assert r[0]["untrained"] is True
    assert (r[1]["type"], r[1]["sev"], r[1]["logger_action"]) == (
        "fault",
        "high",
        "running untrained",
    )


def test_LOG_22_storage_fault_is_logged_after_the_card_returns(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path, plan=[(103.0, "eio", {"ops": ["card_write"], "for_s": 1.0})])
    s.start()
    feed(s, fc, 3)  # now at 103.0: the card fails writes for 1 s
    claim = (0x8000810033A1B2C4).to_bytes(8, "little")
    s.capture._ingest(Frame(1.7e9, fc.mono(), 0x18EEFFF9, True, False, False, claim, False))
    s.step()  # connection_start cannot be written
    fc.advance(1.5)
    feed(s, fc, 2)  # the card is back: the fault is logged
    stop(s)
    faults = [r for r in all_records(tmp_path) if r["type"] == "fault"]
    assert faults and faults[0]["sev"] == "high" and "eio" in faults[0]["cause"]
    verify(all_records(tmp_path))


def test_LOG_3_sync_thread_syncs_every_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    s, fc, _ = make(tmp_path, overrides={"logging.sync_interval_s": 0.02})
    s.start()
    feed(s, fc, 2)  # the header is written once the claim settles
    before = len(synced)
    time.sleep(0.2)
    assert len(synced) - before >= 3
    stop(s)


def test_LOG_5_crash_before_the_header_continues_the_chain_from_the_older_file(
    tmp_path: Path,
) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    feed(s, fc, 2)
    stop(s)
    last = all_records(tmp_path)[-1]["hash"]
    s2, _, _ = make(tmp_path, fc=fc)
    s2.start()  # power lost before the header settled: session 2 file is empty
    s2.capture.stop()
    assert s2.eventlog is not None
    s2.eventlog.close()
    s3, _, _ = make(tmp_path, fc=fc)
    s3.start()
    stop(s3)
    files = session_files(tmp_path / "card" / "sessions")
    assert [f.session for f in files] == [1, 3]  # session 2 never wrote a record
    third = recs(files[-1].path)[0]
    assert (third["session"], third["prev"]) == (3, last)  # the chain continues
    verify(all_records(tmp_path))
