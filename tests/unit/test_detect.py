"""detect (step 1 minimal, DC-9): new NAMEs open connections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from j1939logger.clock import Clock
from j1939logger.detect import Detect, InventoryEntry
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.types import J1939Msg

START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
SCAN_TOOL = 0x8000810033A1B2C4
ENGINE = 0x000000002E412A10
ELD = 0x8000FE003C04D2E8
INVENTORY = {
    ENGINE: InventoryEntry("E01", "vehicle ECU in baseline"),
    ELD: InventoryEntry("E04", "external device (approved)"),
}


def claim(name: int, sa: int, t: float, own: bool = False) -> J1939Msg:
    return J1939Msg(t, 0.0, 6, 60928, sa, 255, name.to_bytes(8, "little"), False, own, False)


def eec1(t: float) -> J1939Msg:
    return J1939Msg(t, 0.0, 3, 61444, 0, 255, bytes(8), False, False, False)


def make(tmp_path: Path, inventory: Optional[dict[int, InventoryEntry]] = INVENTORY) -> Detect:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    return Detect(Clock(DesktopPlatform(clock=fc, root=tmp_path), 5), inventory, 10.0)


def test_DET_1_new_name_late_in_session_is_unrecognized_external_high(tmp_path: Path) -> None:
    d = make(tmp_path)
    assert d.on_message(eec1(100.0)) == []
    [rec] = d.on_message(claim(SCAN_TOOL, 249, 100.0 + 29 * 60))
    assert (rec.type, rec.sev, rec.conn) == ("connection_start", "high", 1)
    f = rec.fields
    assert (f["sa"], f["name"], f["in_inventory"]) == (249, "0x8000810033A1B2C4", False)
    assert f["category"] == "external device (unrecognized)"
    assert f["classification_rule"] == "wake timing"
    assert f["classification_detail"] == "first claim 29 min after the session's first frame"
    assert f["name_fields"]["function"] == 129 and f["name_fields"]["mfr_code"] == 413
    assert rec.utc == START + timedelta(minutes=29)


def test_DET_1_new_name_within_wake_window_is_vehicle_ecu_not_in_baseline(tmp_path: Path) -> None:
    d = make(tmp_path)
    d.on_message(eec1(100.0))
    [rec] = d.on_message(claim(SCAN_TOOL, 249, 103.0))
    assert rec.fields["category"] == "vehicle ECU not in baseline"
    assert rec.fields["trigger"] == "address claim at session start"
    assert rec.sev == "high"


def test_DET_1_baseline_ecu_gets_no_record(tmp_path: Path) -> None:
    d = make(tmp_path)
    assert d.on_message(claim(ENGINE, 0, 100.0)) == []
    assert d.connections == []


def test_DET_17_approved_external_device_gets_info_short_form(tmp_path: Path) -> None:
    d = make(tmp_path)
    [rec] = d.on_message(claim(ELD, 238, 101.2))
    assert (rec.sev, rec.fields["entry"], rec.fields["category"]) == (
        "info",
        "E04",
        "external device (approved)",
    )
    assert "name_fields" not in rec.fields


def test_DET_15_same_name_claiming_again_is_one_connection(tmp_path: Path) -> None:
    d = make(tmp_path)
    assert len(d.on_message(claim(SCAN_TOOL, 249, 200.0))) == 1
    assert d.on_message(claim(SCAN_TOOL, 250, 201.0)) == []
    [conn] = d.connections
    assert (conn.conn, conn.sa, conn.last_mono) == (1, 250, 201.0)


def test_TRN_9_untrained_session_caps_severity_at_notice(tmp_path: Path) -> None:
    d = make(tmp_path, inventory=None)
    [rec] = d.on_message(claim(SCAN_TOOL, 249, 200.0))
    assert rec.sev == "notice"


def test_NP_15_own_claim_is_ignored(tmp_path: Path) -> None:
    d = make(tmp_path)
    assert d.on_message(claim(0x9FFEFFFFFFE00001, 247, 100.0, own=True)) == []
