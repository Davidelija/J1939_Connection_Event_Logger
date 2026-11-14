"""Step 6 in the session: training, operator calls, VIN mismatch, raw captures, retention (PR 3)."""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

import pytest

from j1939logger.config import Inventory, validate_inventory
from j1939logger.inventory import InventoryRefused
from j1939logger.main import inventory_from_file
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import Session, session_files, settings_from_config
from j1939logger.store import CardUsage
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
ENGINE = 0x000000002E412A10  # E01 at SA 0
SCAN = 0x8000810033A1B2C4
VIN = "1XKYD49X0GJ123456"


class _Socket:
    def setsockopt(self, *a: Any) -> None: ...
    def getsockopt(self, *a: Any) -> int:
        return 1 << 20

    def settimeout(self, t: float) -> None: ...
    def recvmsg(self, *a: Any) -> Any:
        time.sleep(0.005)
        raise socket.timeout()

    def send(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None: ...


class Bus(DesktopPlatform):
    def open_can(self, listen_only: bool) -> socket.socket:
        return cast(socket.socket, _Socket())

    def bitrate_check(self) -> Optional[int]:
        return 250000


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def inventory() -> Inventory:
    return inventory_from_file(json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8")))


def make(
    root: Path, inv: Optional[Inventory] = None, trained: bool = True
) -> tuple[Session, FakeClock]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    versions = {"config": "cfg-v3", "inventory": "inv-v2" if trained else None, "library": None}
    chosen = (inv or inventory()) if trained else None
    return Session(Bus(clock=fc, root=root), settings(), chosen, versions, None), fc


def frame(cid: int, data: bytes, t: float) -> Frame:
    return Frame(1.7e9 + t, t, cid, True, False, False, data, False)


def claim(name: int, sa: int, t: float) -> Frame:
    return frame(0x18EEFF00 | sa, name.to_bytes(8, "little"), t)


def pdu2(pgn: int, sa: int, t: float, data: bytes = bytes(8)) -> Frame:
    return frame((6 << 26) | (pgn << 8) | sa, data, t)


def eec1(rpm: float, t: float) -> Frame:
    raw = int(rpm / 0.125)
    return pdu2(61444, 0, t, bytes([0xFF, 0x7D, 0x7D]) + raw.to_bytes(2, "little") + bytes(3))


def bam(sa: int, pgn: int, payload: bytes, t: float) -> list[Frame]:
    packets = (len(payload) + 6) // 7
    cm = bytes([32, len(payload), 0, packets, 0xFF]) + pgn.to_bytes(3, "little")
    out = [frame((7 << 26) | (0xEC << 16) | (0xFF << 8) | sa, cm, t)]
    for i in range(packets):
        chunk = payload[i * 7 : i * 7 + 7].ljust(7, b"\xff")
        out.append(frame((7 << 26) | (0xEB << 16) | (0xFF << 8) | sa, bytes([i + 1]) + chunk,
                         t + 0.05 * (i + 1)))  # fmt: skip
    return out


def run(s: Session, fc: FakeClock, seconds: float, *senders: int, step: float = 0.1) -> None:
    end = fc.mono() + seconds
    while fc.mono() < end:
        for sa in senders:
            s.capture._ingest(pdu2(65262, sa, fc.mono()))
        s.step()
        fc.advance(step)


def records(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in session_files(root / "card" / "sessions"):
        out += [json.loads(x) for x in f.path.read_text("utf-8").splitlines()]
    return out


def started(s: Session, fc: FakeClock) -> None:
    s.start()
    s.capture._ingest(claim(ENGINE, 0, fc.mono()))
    run(s, fc, 3.0, 0)


def stored(root: Path) -> list[str]:
    folder = root / "card" / "inventory"
    return sorted(p.name for p in folder.glob("inv-v*.json")) if folder.is_dir() else []


# -- training and confirmation (TRN-2 to TRN-4, TRN-9, TRN-12) ------------------------


def test_TRN_4_trained_inventory_is_saved_only_when_confirmed(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.train_start("jdoe")
    s.capture._ingest(eec1(700, fc.mono()))
    s.capture._ingest(claim(0x0000110012345678, 17, fc.mono()))
    run(s, fc, 2.0, 0, 17)
    proposal = s.train_finish("jdoe")
    assert proposal["inventory"] == "inv-v3" and stored(tmp_path) == []  # not applied yet
    names = {e["name"] for e in proposal["entries"]}
    assert {"0x000000002E412A10", "0x0000110012345678"} <= names
    engine = next(e for e in proposal["entries"] if e["name"] == "0x000000002E412A10")
    assert engine["entry"] == "E01" and "idle" in engine["states_seen"]
    assert s.confirm_inventory("jdoe", apply=True) == "inv-v3"
    assert stored(tmp_path) == ["inv-v3.json"]
    saved = json.loads((tmp_path / "card" / "inventory" / "inv-v3.json").read_text("utf-8"))
    assert isinstance(validate_inventory(saved), Inventory)
    recs = records(tmp_path)
    types = [r["type"] for r in recs]
    assert types.index("training_start") < types.index("training_finish") < types.index("approval")
    finish = next(r for r in recs if r["type"] == "training_finish")
    assert finish["inventory_proposed"] == "inv-v3" and finish["timed_out"] is False
    assert "key-on engine off" in finish["states_covered"] and "idle" in finish["states_covered"]
    approval = next(r for r in recs if r["type"] == "approval")
    assert (approval["kind"], approval["new_inventory"], approval["sev"]) == (
        "inventory", "inv-v3", "notice",
    )  # fmt: skip


def test_TRN_4_rejected_inventory_is_not_applied(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.train_start("jdoe")
    run(s, fc, 1.0, 0)
    s.train_finish("jdoe")
    assert s.confirm_inventory("jdoe", apply=False, reason="ELD was plugged in") is None
    assert stored(tmp_path) == []
    [rej] = [r for r in records(tmp_path) if r["type"] == "rejection"]
    assert rej["proposed_inventory"] == "inv-v3" and rej["reason"] == "ELD was plugged in"
    with pytest.raises(InventoryRefused):
        s.confirm_inventory("jdoe", apply=True)  # nothing left to confirm


def test_TRN_9_training_runs_detection_as_untrained(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.train_start("jdoe")
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 1.0, 0, 249)
    [start] = [r for r in records(tmp_path) if r["type"] == "connection_start" and r["sa"] == 249]
    assert start["sev"] == "notice"  # capped while untrained


def test_TRN_11_nothing_is_added_without_an_operator_call(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 40.0, 0, 249)
    assert stored(tmp_path) == []
    assert not [r for r in records(tmp_path) if r["type"] in ("approval", "training_start")]


# -- approvals and removals (TRN-10, TRN-14) ------------------------------------------


def test_TRN_10_approving_a_logged_new_pgn_saves_the_next_version(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(pdu2(0xFE6C, 0, fc.mono()))  # 65132, new for E01
    run(s, fc, 0.5, 0)
    [event] = [r for r in records(tmp_path) if r["type"] == "known_device_new_pgn"]
    version = s.approve(f"1-{event['rec']}", "jdoe", "RO 7001")
    assert version == "inv-v3" and stored(tmp_path) == ["inv-v3.json"]
    saved = json.loads((tmp_path / "card" / "inventory" / "inv-v3.json").read_text("utf-8"))
    assert {"pgn": 65132, "kind": "PGN sent"}.items() <= saved["entries"][0]["pgns_approved"][
        -1
    ].items()
    [approval] = [r for r in records(tmp_path) if r["type"] == "approval"]
    assert approval["events_cleared"] == [f"1-{event['rec']}"]
    with pytest.raises(InventoryRefused, match="not found"):
        s.approve("1-999", "jdoe", "r")


def test_TRN_14_removing_an_entry_saves_the_next_version(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    assert s.remove("E03", "jdoe", "ECU replaced") == "inv-v3"
    s.remove("E01", "jdoe", "not fitted", pgn=65226, direction="sent")
    assert stored(tmp_path) == ["inv-v3.json", "inv-v4.json"]
    v4 = json.loads((tmp_path / "card" / "inventory" / "inv-v4.json").read_text("utf-8"))
    assert "E03" not in [e["entry"] for e in v4["entries"]]  # v4 builds on v3
    removes = [r for r in records(tmp_path) if r["type"] == "inventory_remove"]
    assert [r["new_inventory"] for r in removes] == ["inv-v3", "inv-v4"]


# -- DET-14: VIN mismatch ---------------------------------------------------------------


def test_DET_14_vin_mismatch_is_high_and_the_session_runs_untrained(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    run(s, fc, 1.0, 0)
    for f in bam(0x00, 65260, b"9ZZZZ00000Z000000*", fc.mono()):
        s.capture._ingest(f)
    run(s, fc, 1.0, 0)
    recs = records(tmp_path)
    [check] = [r for r in recs if r["type"] == "vin_check"]
    assert check["vin_status"] == "mismatch"
    [mismatch] = [r for r in recs if r["type"] == "vin_mismatch"]
    assert (mismatch["sev"], mismatch["inventory_vin"]) == ("high", VIN)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 1.0, 0, 249)
    [start] = [r for r in records(tmp_path) if r["type"] == "connection_start" and r["sa"] == 249]
    assert start["sev"] == "notice"  # untrained for the rest of the session


# -- LOG-10, LOG-22: raw captures and retention -----------------------------------------


def test_LOG_10_connection_start_names_its_raw_capture_and_the_file_is_written(
    tmp_path: Path,
) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 62.0, 0, 249)
    [start] = [r for r in records(tmp_path) if r["type"] == "connection_start"]
    assert start["raw_capture"] == "raw/s000001_c1_e1.log"
    lines = (tmp_path / "card" / start["raw_capture"]).read_text("ascii").splitlines()
    times = [float(x[1:18]) - 1.7e9 for x in lines]
    t_event = (datetime.fromisoformat(start["utc"].replace("Z", "+00:00")) - START).total_seconds()
    assert min(times) <= 100.0 + t_event <= max(times)  # the window contains the record's utc


def test_LOG_22_retention_stops_raw_captures_when_only_the_reserve_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, fc = make(tmp_path)
    monkeypatch.setattr(
        s.store, "usage", lambda: CardUsage(8000 * 2**20, 7600 * 2**20, 400 * 2**20)
    )
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 1.0, 0, 249)
    recs = records(tmp_path)
    causes = [(r["sev"], r["cause"]) for r in recs if r["type"] == "fault"]
    assert ("notice", "card nearly full (95.0% used)") in causes
    assert ("high", "card full; raw captures stopped") in causes
    [start] = [r for r in recs if r["type"] == "connection_start"]
    assert start["raw_capture"] is None
