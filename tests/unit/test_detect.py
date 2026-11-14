"""detect (step 4 PR 2, DC-13): connections start, move and end."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.clock import Clock
from j1939logger.config import Inventory, InventoryEntry, validate_inventory
from j1939logger.detect import Detect
from j1939logger.monitor import Monitor
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import settings_from_config
from j1939logger.types import J1939Msg

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
SCAN_TOOL = 0x8000810033A1B2C4
ENGINE = 0x000000002E412A10  # E01 at SA 0
TRANS = 0x000003001D20B4F1  # E02 at SA 3
ELD = 0x8000FE003C04D2E8  # E04 at SA 238, approved
LOGGER = 0x9FFEFFFFFFE00001


def settings(**over: Any) -> dict[str, Any]:
    s = settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))
    s.update(over)
    return s


def inventory(extra: tuple[InventoryEntry, ...] = ()) -> Inventory:
    inv = validate_inventory(json.loads((EXAMPLES / "inv-v2.json").read_text(encoding="utf-8")))
    assert isinstance(inv, Inventory)
    return Inventory(inv.version, inv.vin, inv.entries + extra)


def claim(name: int, sa: int, t: float, own: bool = False) -> J1939Msg:
    return J1939Msg(t, 0.0, 6, 60928, sa, 255, name.to_bytes(8, "little"), False, own, False)


def frame(sa: int, t: float, pgn: int = 61444, da: int = 255) -> J1939Msg:
    return J1939Msg(t, 0.0, 3, pgn, sa, da, bytes(8), False, False, False)


def make(
    tmp_path: Path,
    inv: Optional[Inventory] = None,
    untrained: bool = False,
    monitor: bool = False,
    **over: Any,
) -> tuple[Detect, Optional[Monitor]]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    clock = Clock(DesktopPlatform(clock=fc, root=tmp_path), 5)
    s = settings(**over)
    inventory_ = None if untrained else (inv or inventory())
    mon = Monitor(clock, s, inventory_) if monitor else None
    d = Detect(clock, s, inventory_, mon.end if mon else None, ready_mono=100.0)
    return d, mon


def started(d: Detect, *msgs: J1939Msg, logger_sa: Optional[int] = 247) -> list[Any]:
    out = []
    for m in msgs:
        out += d.on_message(m, logger_sa)
    return out


# -- DET-1, DET-15, DET-17 ---------------------------------------------------


def test_DET_1_new_name_late_in_session_is_unrecognized_external_high(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    assert started(d, frame(0, 100.0)) == []
    [rec] = started(d, claim(SCAN_TOOL, 249, 100.0 + 29 * 60))
    assert (rec.type, rec.sev, rec.conn) == ("connection_start", "high", 1)
    f = rec.fields
    assert (f["sa"], f["name"], f["in_inventory"]) == (249, "0x8000810033A1B2C4", False)
    assert f["trigger"] == "new address claim during steady state"
    assert f["category"] == "external device (unrecognized)"
    assert f["classification_detail"] == "first claim 29 min after the session's first frame"
    assert rec.utc == START + timedelta(minutes=29)


def test_DET_1_new_name_within_wake_window_is_vehicle_ecu_not_in_baseline(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    [rec] = started(d, frame(0, 100.0), claim(SCAN_TOOL, 249, 103.0))
    assert rec.fields["category"] == "vehicle ECU not in baseline"
    assert rec.fields["trigger"] == "address claim at session start"


def test_DET_1_baseline_ecu_gets_no_record(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    assert started(d, claim(ENGINE, 0, 100.0), frame(0, 100.1)) == []
    assert d.connections == [] and d.name_at(0) == ENGINE
    assert d.entry_for(0) is not None and d.entry_for(0).entry == "E01"  # type: ignore[union-attr]


def test_DET_17_approved_external_device_gets_info_short_form(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    [rec] = started(d, claim(ELD, 238, 101.2))
    assert (rec.sev, rec.fields["entry"], rec.fields["category"]) == (
        "info", "E04", "external device (approved)",
    )  # fmt: skip
    assert "name_fields" not in rec.fields


def test_DET_15_same_name_claiming_again_is_one_connection(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    assert len(started(d, claim(SCAN_TOOL, 249, 200.0))) == 1
    assert started(d, claim(SCAN_TOOL, 249, 201.0)) == []
    [conn] = d.connections
    assert (conn.conn, conn.sa, conn.last_mono) == (1, 249, 201.0)


def test_DET_15_non_claiming_device_that_claims_keeps_its_connection(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    d.sweep_complete(101.0)
    [rec] = started(d, frame(200, 300.0))
    assert (
        rec.fields["name"] is None and rec.fields["trigger"] == "traffic without an address claim"
    )
    assert started(d, claim(SCAN_TOOL, 200, 301.0)) == []
    [conn] = d.connections
    assert conn.key == ("name", SCAN_TOOL) and conn.conn == rec.conn
    assert d.connection_for(200) is conn


def test_DET_15_returning_device_starts_a_new_connection(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(SCAN_TOOL, 249, 200.0))
    started(d, frame(0, 261.0))
    [end] = d.poll(261.0)
    assert end.fields["end_reason"] == "silence"
    [again] = started(d, frame(249, 300.0))
    assert again.conn == 2 and again.fields["trigger"] == "returned after connection end"


def test_TRN_9_untrained_session_caps_severity_at_notice(tmp_path: Path) -> None:
    d, _ = make(tmp_path, untrained=True)
    [rec] = started(d, claim(SCAN_TOOL, 249, 200.0))
    assert rec.sev == "notice"


def test_NP_15_own_frames_are_ignored(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    d.sweep_complete(101.0)
    assert started(d, claim(LOGGER, 247, 102.0, own=True)) == []
    own = J1939Msg(103.0, 0.0, 6, 59904, 247, 77, b"\x00\xee\x00", False, True, False)
    assert started(d, own) == [] and d.connections == []


# -- DET-2: the first-sweep wait ---------------------------------------------


def test_DET_2_unclaimed_address_waits_for_the_first_sweep(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    assert started(d, frame(200, 100.5), frame(200, 100.9)) == []
    assert d.waiting
    [rec] = d.sweep_complete(102.25)
    assert rec.fields["sa"] == 200 and rec.fields["trigger"] == "traffic without an address claim"
    assert rec.utc == START + timedelta(seconds=0.5)  # first frame


def test_DET_2_inventory_address_without_a_claim_after_the_sweep_is_detected(
    tmp_path: Path,
) -> None:
    d, _ = make(tmp_path)
    started(d, frame(3, 100.5))  # E02's stored address, but no claim this session
    started(d, claim(ENGINE, 0, 100.6), frame(0, 100.7))
    [rec] = d.sweep_complete(102.25)
    assert rec.fields["sa"] == 3  # addresses are hints only; E01 at 0 claimed


def test_DET_2_no_sweep_keeps_inventory_addresses_and_waits_first_sweep_wait_s(
    tmp_path: Path,
) -> None:
    d, _ = make(tmp_path)
    d.no_sweep()
    started(d, frame(3, 100.5), frame(200, 100.6))
    assert d.poll(105.0) == []
    [rec] = d.poll(110.0)  # ready 100.0 + detection.first_sweep_wait_s 10
    assert rec.fields["sa"] == 200
    assert d.entry_for(3) is not None  # still a match for the session
    assert started(d, frame(3, 111.0)) == []


def test_DET_2_never_claiming_inventory_entry_is_known_by_address(tmp_path: Path) -> None:
    never = InventoryEntry("E09", None, "vehicle ECU in baseline", (40,), (65000,))
    d, _ = make(tmp_path, inv=inventory((never,)))
    started(d, frame(40, 100.5))
    assert d.sweep_complete(102.25) == []
    assert started(d, frame(40, 103.0)) == []
    assert d.entry_for(40) is never


# -- DET-3 ---------------------------------------------------------------------


def test_DET_3_reply_to_an_unclaimed_address_opens_a_connection(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(ENGINE, 0, 100.1))
    d.sweep_complete(101.5)
    [rec] = started(d, frame(0, 120.0, pgn=59392, da=77))
    assert rec.fields["sa"] == 77 and rec.fields["trigger"] == "replies sent to SA 77"
    assert d.connection_for(77) is not None


def test_DET_3_global_null_logger_and_claimed_addresses_are_excluded(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(ENGINE, 0, 100.1), claim(TRANS, 3, 100.2))
    d.sweep_complete(101.5)
    for da in (254, 247, 3):
        assert started(d, frame(0, 120.0, pgn=59392, da=da)) == []
    reply = J1939Msg(121.0, 0.0, 6, 59392, 0, 247, bytes(8), False, False, True)
    assert started(d, reply) == []


# -- DET-4 ---------------------------------------------------------------------


def test_DET_4_known_name_at_a_new_address_is_confirmed_after_the_grace(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(TRANS, 3, 100.1), frame(3, 100.2))
    d.sweep_complete(101.5)
    assert started(d, claim(TRANS, 5, 200.0)) == []
    assert d.poll(200.5) == []  # inside detection.move_grace_s
    [rec] = d.poll(201.1)
    assert (rec.type, rec.sev) == ("address_change", "info")
    assert rec.fields == {"name": "0x000003001D20B4F1", "entry": "E02", "old_sa": 3, "new_sa": 5}
    started(d, claim(TRANS, 3, 300.0), claim(TRANS, 5, 300.5))
    assert d.poll(400.0) == []  # once per NAME and address


def test_DET_4_move_to_another_known_ecus_address_is_notice(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(TRANS, 3, 100.1))
    d.sweep_complete(101.5)
    started(d, claim(TRANS, 11, 200.0))  # 11 is E03's stored address
    [rec] = d.poll(202.0)
    assert rec.sev == "notice"


def test_DET_4_old_address_still_sending_is_same_name_conflict(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(TRANS, 3, 100.1))
    d.sweep_complete(101.5)
    started(d, claim(TRANS, 5, 200.0), frame(3, 200.4))
    [rec] = d.poll(201.5)
    assert (rec.type, rec.sev) == ("address_conflict", "high")
    assert rec.fields["cause"] == "same NAME at two addresses" and rec.fields["sa"] == [3, 5]


def test_DET_4_frame_from_the_old_address_after_a_confirmed_move_conflicts(
    tmp_path: Path,
) -> None:
    d, _ = make(tmp_path)
    started(d, claim(TRANS, 3, 100.1))
    d.sweep_complete(101.5)
    started(d, claim(TRANS, 5, 200.0))
    [change] = d.poll(202.0)
    [rec] = started(d, claim(TRANS, 3, 260.0))  # both answer a sweep
    assert rec.fields["cause"] == "same NAME at two addresses"
    assert started(d, frame(3, 261.0)) == []  # once per pair


def test_DET_4_old_address_claimed_by_another_name_is_not_a_conflict(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(TRANS, 3, 100.1))
    d.sweep_complete(101.5)
    started(d, claim(TRANS, 5, 200.0))
    d.poll(202.0)
    [rec] = started(d, claim(SCAN_TOOL, 3, 300.0))
    assert rec.type == "connection_start"
    assert started(d, frame(3, 301.0)) == []


def test_DET_4_two_names_at_one_address(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(ENGINE, 0, 100.1))
    d.sweep_complete(101.5)
    recs = started(d, claim(SCAN_TOOL, 0, 200.0))
    [conflict] = [r for r in recs if r.type == "address_conflict"]
    assert conflict.sev == "notice"  # ENGINE has the lower NAME and keeps 0
    assert conflict.fields["winner"] == "0x000000002E412A10"
    assert d.name_at(0) == ENGINE


# -- DET-6 ---------------------------------------------------------------------


def test_DET_6_silence_end_while_the_bus_is_active(tmp_path: Path) -> None:
    d, mon = make(tmp_path, monitor=True)
    assert mon is not None
    [start] = started(d, claim(SCAN_TOOL, 249, 200.0))
    conn = d.connection_for(249)
    mon.on_message(frame(249, 200.5, pgn=65262), conn)
    started(d, frame(249, 200.5))
    started(d, frame(0, 250.0))
    assert d.poll(250.0) == []  # bus active, 49.5 s
    started(d, frame(0, 260.6))
    [end] = d.poll(260.6)
    assert (end.type, end.sev, end.conn) == ("connection_end", "high", start.conn)
    f = end.fields
    assert (f["end_reason"], f["duration_s"]) == ("silence", 0.5)
    assert f["end"] == "2026-11-06T14:03:51.500Z"
    assert [p["pgn"] for p in f["pgns_sent"]] == [65262]
    assert end.utc == START + timedelta(seconds=160.6)
    assert d.connections == []


def test_DET_6_no_silence_end_when_the_bus_is_quiet(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(SCAN_TOOL, 249, 200.0))
    assert d.poll(400.0) == []  # no other frames: key-off, not silence


def test_DET_6_key_off_ends_every_open_connection(tmp_path: Path) -> None:
    d, _ = make(tmp_path)
    started(d, claim(SCAN_TOOL, 249, 200.0), claim(ELD, 238, 201.0), frame(249, 230.0))
    ends = d.end_all("key-off")
    assert [e.fields["end_reason"] for e in ends] == ["key-off", "key-off"]
    scan = next(e for e in ends if e.fields["sa"] == 249)
    assert scan.fields["end"] == "2026-11-06T14:04:21.000Z"  # last frame, 230.0
    eld = next(e for e in ends if e.fields["sa"] == 238)
    assert eld.sev == "info" and eld.fields["entry"] == "E04"  # DET-17
    assert set(eld.fields) == {"sa", "entry", "start", "end", "end_reason", "duration_s",
                               "new_pgns"}  # fmt: skip


def test_DET_16_record_follows_the_example_connection_start_fields(tmp_path: Path) -> None:
    lines = (EXAMPLES / "s000142_20261106T140211Z.jsonl").read_text(encoding="utf-8")
    example = next(r for r in map(json.loads, lines.splitlines()) if r["rec"] == 5)
    d, _ = make(tmp_path)
    started(d, frame(0, 100.0))
    [rec] = started(d, claim(SCAN_TOOL, 249, 100.0 + 29 * 60))
    skip = {"rec", "type", "sev", "utc", "written", "veh_time", "conn", "prev", "hash"}
    skip |= {"clock_valid", "clock_source", "raw_capture"}  # eventlog; rawcap in step 6
    assert {k: v for k, v in example.items() if k not in skip} == rec.fields
