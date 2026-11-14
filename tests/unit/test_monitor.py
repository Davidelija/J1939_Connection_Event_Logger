"""monitor (step 4 PR 1, DC-13, DC-14): what each connected device does."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from j1939logger.clock import Clock
from j1939logger.config import Inventory, validate_inventory
from j1939logger.monitor import Monitor, is_proprietary
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.types import Connection, J1939Msg

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 31, 40, 118000, tzinfo=timezone.utc)
SETTINGS: dict[str, Any] = {
    "detection.control_pgns": [0, 256, 1024, 65240, 56832, 65235],
    "detection.requests_kept": 100,
    "detection.known_device_new_pgn": True,
    "limits.pgns_per_conn": 2000,
    "limits.tp_sessions": 32,
}
SCAN = Connection(2, ("sa", 249), 249, None, 100.0, 100.0, "external device (unrecognized)")
ELD = Connection(1, ("name", 0x8000FE003C04D2E8), 238, None, 100.0, 100.0,
                 "external device (approved)")  # fmt: skip


def inventory() -> Inventory:
    inv = validate_inventory(json.loads((EXAMPLES / "inv-v2.json").read_text(encoding="utf-8")))
    assert isinstance(inv, Inventory)
    return inv


def entry(eid: str) -> Any:
    return next(e for e in inventory().entries if e.entry == eid)


def make(tmp_path: Path, **over: Any) -> Monitor:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    clock = Clock(DesktopPlatform(clock=fc, root=tmp_path), 5)
    return Monitor(clock, {**SETTINGS, **over}, inventory())


def msg(
    pgn: int,
    sa: int = 249,
    da: int = 255,
    data: bytes = bytes(8),
    t: float = 100.0,
    via_tp: bool = False,
    own: bool = False,
    reply: bool = False,
) -> J1939Msg:
    return J1939Msg(t, 0.0, 6, pgn, sa, da, data, via_tp, own, reply)


def request(pgn: int, sa: int = 249, da: int = 255, t: float = 100.0) -> J1939Msg:
    return msg(59904, sa, da, pgn.to_bytes(3, "little"), t)


def etp_cm(control: int, pgn: int, sa: int, da: int, size: int = 4000) -> J1939Msg:
    data = bytes([control]) + size.to_bytes(4, "little") + pgn.to_bytes(3, "little")
    return msg(51200, sa, da, data)


def test_DET_7_each_pgn_with_first_last_and_count(tmp_path: Path) -> None:
    m = make(tmp_path)
    for t in (100.0, 101.5, 103.25):
        m.on_message(msg(61444, t=t), SCAN)
    m.on_message(msg(65262, t=102.0), SCAN)
    s = m.summary(2)
    assert s["pgns_sent"] == [
        {"pgn": 61444, "name": None, "first": "2026-11-06T14:31:40.118Z",
         "last": "2026-11-06T14:31:43.368Z", "count": 3},
        {"pgn": 65262, "name": None, "first": "2026-11-06T14:31:42.118Z",
         "last": "2026-11-06T14:31:42.118Z", "count": 1},
    ]  # fmt: skip
    assert s["pgns_dropped"] == 0


def test_DET_8_first_requests_kept_in_order_and_the_rest_counted(tmp_path: Path) -> None:
    m = make(tmp_path, **{"detection.requests_kept": 3})
    m.on_message(request(65260, da=0), SCAN)
    m.on_message(request(65259), SCAN)
    m.on_message(request(65227, da=3), SCAN)
    m.on_message(request(61444, da=11), SCAN)
    m.on_message(request(65226), SCAN)
    s = m.summary(2)
    assert s["requests_first_100"] == [
        "65260 VIN -> SA 0", "65259 Component ID -> global", "65227 DM2 -> SA 3",
    ]  # fmt: skip
    assert s["requests_dropped"] == 2
    assert s["ecus_contacted"] == [0, 3, 11]


def test_DET_8_request_for_an_unnamed_pgn_has_no_name(tmp_path: Path) -> None:
    m = make(tmp_path)
    m.on_message(request(61444, da=0), SCAN)
    assert m.summary(2)["requests_first_100"] == ["61444 -> SA 0"]


def test_DET_9_control_pgn_requested_flags_once_with_a_running_count(tmp_path: Path) -> None:
    m = make(tmp_path)
    [rec] = m.on_message(request(65235, da=0, t=100.0), SCAN)
    assert rec.type == "control_flag" and rec.sev == "high" and rec.conn == 2
    assert rec.fields == {
        "sa": 249, "pgn": 65235, "pgn_name": "DM11 clear codes", "target_sa": 0,
        "via": "requested", "count": 1, "raw_capture": None,
    }  # fmt: skip
    assert m.on_message(request(65235, da=0, t=101.0), SCAN) == []
    assert m.summary(2)["control_flags"] == [
        {"pgn": 65235, "name": "DM11 clear codes", "target_sa": 0,
         "first": "2026-11-06T14:31:40.118Z", "count": 2},
    ]  # fmt: skip


def test_DET_9_how_a_control_pgn_was_sent(tmp_path: Path) -> None:
    m = make(tmp_path)
    [single] = m.on_message(msg(0, da=0), SCAN)
    [bam] = m.on_message(msg(56832, via_tp=True), SCAN)
    [rts] = m.on_message(msg(1024, da=11, via_tp=True), SCAN)
    assert single.fields["via"] == "single frame" and single.fields["target_sa"] == 0
    assert bam.fields["via"] == "transport (BAM)" and bam.fields["target_sa"] is None
    assert rts.fields["via"] == "transport (RTS/CTS)"


def test_DET_9_known_device_flags_only_untrained_control_pgns(tmp_path: Path) -> None:
    m = make(tmp_path, **{"detection.known_device_new_pgn": False})
    e01 = entry("E01")  # trained: 65226 among others, never TSC1
    [rec] = m.on_message(msg(0, sa=0, da=3), None, e01)
    assert rec.type == "control_flag" and rec.conn is None and rec.fields["sa"] == 0
    assert m.on_message(msg(0, sa=0, da=3), None, e01) == []
    assert m.on_message(msg(65226, sa=0), None, e01) == []  # not a control PGN


def test_DET_10_dm_activity_and_etp_with_the_memory_transfer_flag(tmp_path: Path) -> None:
    m = make(tmp_path)
    m.on_message(request(65226), SCAN)
    m.on_message(request(65227, da=0), SCAN)
    m.on_message(msg(55552, da=0), SCAN)  # DM14 memory access
    m.on_message(etp_cm(20, 55296, 249, 0, 4000), SCAN)  # RTS
    m.on_message(msg(50944, da=0), SCAN)  # ETP.DT, not tabled
    m.on_message(etp_cm(23, 55296, 0, 249, 4000), None)  # EOMA from the receiver
    m.on_message(etp_cm(20, 61184, 249, 3, 2000), SCAN)
    m.on_message(etp_cm(255, 61184, 3, 249), None)  # Abort from the receiver
    m.on_message(etp_cm(20, 65280, 249, 11, 3000), SCAN)  # still open at the end
    s = m.end(2)
    assert s["dm_types"] == ["DM1", "DM2", "DM14"]
    assert s["etp_transfers"] == [
        {"sender": 249, "destination": 0, "pgn": 55296, "bytes": 4000, "result": "completed",
         "memory_transfer": True},
        {"sender": 249, "destination": 3, "pgn": 61184, "bytes": 2000, "result": "aborted",
         "memory_transfer": True},
        {"sender": 249, "destination": 11, "pgn": 65280, "bytes": 3000, "result": "aborted",
         "memory_transfer": True},
    ]  # fmt: skip
    assert 50944 not in {p["pgn"] for p in s["pgns_sent"]}
    assert m.open_transfers == 0


def test_DET_10_no_memory_flag_without_dm14_to_dm16(tmp_path: Path) -> None:
    m = make(tmp_path)
    m.on_message(etp_cm(20, 61184, 249, 0), SCAN)
    m.on_message(etp_cm(23, 61184, 0, 249), None)
    [t] = m.summary(2)["etp_transfers"]
    assert t["result"] == "completed" and t["memory_transfer"] is False


def test_DET_11_proprietary_pgns_listed(tmp_path: Path) -> None:
    m = make(tmp_path)
    for pgn in (65300, 61184, 65280, 65300, 61444):
        m.on_message(msg(pgn, data=b"\xff" * 8), SCAN)
    assert m.summary(2)["proprietary_pgns"] == [61184, 65280, 65300]
    assert is_proprietary(65535) and not is_proprietary(65279) and not is_proprietary(61185)


def test_DET_12_known_name_sending_an_untrained_pgn_once_per_session(tmp_path: Path) -> None:
    m = make(tmp_path)
    e01 = entry("E01")
    assert m.on_message(msg(61444, sa=0), None, e01) == []  # trained
    assert m.on_message(msg(64892, sa=0), None, e01) == []  # approved "PGN sent"
    [rec] = m.on_message(msg(65132, sa=0), None, e01)
    assert rec.type == "known_device_new_pgn" and rec.sev == "notice"
    assert rec.fields == {
        "sa": 0, "name": "0x000000002E412A10", "entry": "E01", "pgn": 65132,
        "pgn_name": None, "direction": "sent", "count": 1,
    }  # fmt: skip
    assert m.on_message(msg(65132, sa=0, t=200.0), None, e01) == []


def test_DET_12_approved_device_requesting_outside_its_trained_set(tmp_path: Path) -> None:
    m = make(tmp_path)
    e04 = entry("E04")
    assert m.on_message(request(65260, sa=238, da=0), ELD, e04) == []  # trained request
    [rec] = m.on_message(request(65227, sa=238, da=0), ELD, e04)
    assert rec.fields["direction"] == "requested" and rec.fields["pgn"] == 65227
    assert rec.conn == 1
    assert m.summary(1) == {"new_pgns": [{"pgn": 65227, "name": "DM2", "direction": "requested"}]}


def test_DET_12_switch_off_gives_no_new_pgn_records(tmp_path: Path) -> None:
    m = make(tmp_path, **{"detection.known_device_new_pgn": False})
    assert m.on_message(msg(65132, sa=0), None, entry("E01")) == []


def test_DET_19_pgn_table_is_bounded_and_the_rest_counted(tmp_path: Path) -> None:
    m = make(tmp_path, **{"limits.pgns_per_conn": 3})
    for pgn in (61444, 65262, 65265, 65270, 65271, 61444):
        m.on_message(msg(pgn), SCAN)
    s = m.summary(2)
    assert [p["pgn"] for p in s["pgns_sent"]] == [61444, 65262, 65265]
    assert s["pgns_sent"][0]["count"] == 2
    assert s["pgns_dropped"] == 2


def test_DET_19_open_etp_transfers_are_bounded(tmp_path: Path) -> None:
    m = make(tmp_path, **{"limits.tp_sessions": 2})
    for da in (0, 3, 11, 23):
        m.on_message(etp_cm(20, 61184, 249, da), SCAN)
    assert m.open_transfers == 2
    assert len(m.summary(2)["etp_transfers"]) == 2


def test_NP_15_own_frames_and_replies_to_the_logger_are_not_monitored(tmp_path: Path) -> None:
    m = make(tmp_path)
    assert m.on_message(msg(0, own=True), SCAN) == []
    assert m.on_message(msg(0, da=247, reply=True), SCAN) == []
    assert m.summary(2)["pgns_sent"] == []


def test_DET_7_summary_matches_the_example_connection_end_fields(tmp_path: Path) -> None:
    lines = (EXAMPLES / "s000142_20261106T140211Z.jsonl").read_text(encoding="utf-8")
    end = next(r for r in map(json.loads, lines.splitlines()) if r["rec"] == 9)
    m = make(tmp_path)
    m.on_message(request(65235, da=0), SCAN)
    keys = set(m.summary(2))
    example = {k for k in end if k in keys or k in {"pgns_sent", "dm_types", "new_pgns"}}
    assert example <= keys  # every activity field in the example is produced
    assert keys - set(end) == {"pgns_dropped"}  # added by DC-13
