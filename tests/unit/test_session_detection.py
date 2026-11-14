"""Step 4 in the session: detect and monitor driven by the main loop (step 4 PR 3)."""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

from j1939logger.config import Inventory
from j1939logger.main import inventory_from_file
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import Session, session_files, settings_from_config
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
ENGINE = 0x000000002E412A10  # E01 at SA 0
SCAN = 0x8000810033A1B2C4


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
    def __init__(self, rate: Optional[int] = 250000, **kw: Any) -> None:
        super().__init__(**kw)
        self.rate = rate

    def open_can(self, listen_only: bool) -> socket.socket:
        return cast(socket.socket, _Socket())

    def bitrate_check(self) -> Optional[int]:
        return self.rate


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def inventory() -> Inventory:
    return inventory_from_file(json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8")))


def make(root: Path, rate: Optional[int] = 250000) -> tuple[Session, FakeClock]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    versions = {"config": "cfg-v3", "inventory": "inv-v2", "library": "lib-v1"}
    return Session(Bus(rate, clock=fc, root=root), settings(), inventory(), versions, None), fc


def frame(cid: int, data: bytes, t: float) -> Frame:
    return Frame(1.7e9 + t, t, cid, True, False, False, data, False)


def claim(name: int, sa: int, t: float) -> Frame:
    return frame(0x18EEFF00 | sa, name.to_bytes(8, "little"), t)


def request(pgn: int, sa: int, da: int, t: float) -> Frame:
    return frame((6 << 26) | (0xEA << 16) | (da << 8) | sa, pgn.to_bytes(3, "little"), t)


def pdu2(pgn: int, sa: int, t: float) -> Frame:
    return frame((6 << 26) | (pgn << 8) | sa, bytes(8), t)


def run(s: Session, fc: FakeClock, seconds: float, *senders: int, step: float = 0.1) -> None:
    """Advance time; each SA in ``senders`` sends EEC1-like traffic every step."""
    end = fc.mono() + seconds
    while fc.mono() < end:
        for sa in senders:
            s.capture._ingest(pdu2(61444, sa, fc.mono()))
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
    run(s, fc, 3.0, 0)  # claim settles and the first sweep completes


def test_DET_6_key_off_ends_the_connection_before_session_end(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 1.0, 0)
    s.capture._ingest(request(65235, 249, 0, fc.mono()))  # DM11 clear codes to the engine
    s.capture._ingest(request(65227, 249, 0, fc.mono()))
    last = fc.mono()
    run(s, fc, 1.0, 0)
    run(s, fc, 31.0)  # bus silent: key-off after session.end_silence_s
    recs = records(tmp_path)
    types = [r["type"] for r in recs]
    assert types.index("connection_start") < types.index("control_flag")
    assert types.index("control_flag") < types.index("connection_end")
    assert types.index("connection_end") < types.index("session_end")
    end = next(r for r in recs if r["type"] == "connection_end")
    assert (end["sa"], end["end_reason"], end["sev"]) == (249, "key-off", "high")
    assert end["requests_first_100"] == ["65235 DM11 -> SA 0", "65227 DM2 -> SA 0"]
    assert end["dm_types"] == ["DM11", "DM2"] and end["ecus_contacted"] == [0]
    assert end["control_flags"][0]["name"] == "DM11 clear codes"
    assert end["end"] < end["utc"]  # the end is the last frame, recorded at key-off
    assert abs(end["duration_s"] - (last - (last - 1.0))) < 0.2
    flag = next(r for r in recs if r["type"] == "control_flag")
    assert (flag["via"], flag["target_sa"]) == ("requested", 0)
    assert flag["raw_capture"] == "raw/s000001_c1_e2.log"  # rawcap, step 6 (DC-20)
    session_end = next(r for r in recs if r["type"] == "session_end")
    assert session_end["connections"] == 1


def test_DET_6_silence_end_while_the_bus_is_active(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 1.0, 0, 249)
    run(s, fc, 61.0, 0)  # the engine keeps sending; the scan tool is silent
    [end] = [r for r in records(tmp_path) if r["type"] == "connection_end"]
    assert end["end_reason"] == "silence"
    assert [p["pgn"] for p in end["pgns_sent"]] == [60928, 61444]  # DC-15: carried PGNs
    assert s.detect is not None and s.detect.connections == []


def test_DET_2_unclaimed_address_is_detected_when_the_first_sweep_completes(
    tmp_path: Path,
) -> None:
    s, fc = make(tmp_path)
    s.start()
    s.capture._ingest(claim(ENGINE, 0, fc.mono()))
    run(s, fc, 0.3, 0, 200)
    assert not [r for r in records(tmp_path) if r["type"] == "connection_start"]
    run(s, fc, 3.0, 0, 200)
    assert s.requests is not None and s.requests.first_sweep_done
    [start] = [r for r in records(tmp_path) if r["type"] == "connection_start"]
    assert (start["sa"], start["name"]) == (200, None)
    assert start["trigger"] == "traffic without an address claim"


def test_DET_2_without_a_bit_rate_the_wait_ends_after_first_sweep_wait_s(tmp_path: Path) -> None:
    s, fc = make(tmp_path, rate=None)
    s.start()
    run(s, fc, 9.0, 0, 200)
    assert not [r for r in records(tmp_path) if r["type"] == "connection_start"]
    run(s, fc, 2.0, 0, 200)
    starts = [r for r in records(tmp_path) if r["type"] == "connection_start"]
    assert [r["sa"] for r in starts] == [200]  # SA 0 stays matched to E01 (DET-2)


def test_DET_12_known_ecu_sending_a_new_pgn_in_the_session(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(pdu2(0xFE6C, 0, fc.mono()))  # 65132: not in E01's trained set
    run(s, fc, 0.5, 0)
    [rec] = [r for r in records(tmp_path) if r["type"] == "known_device_new_pgn"]
    assert (rec["sa"], rec["entry"], rec["pgn"], rec["direction"]) == (0, "E01", 65132, "sent")
    assert "conn" not in rec  # a known ECU has no connection


def test_LOG_7_connection_records_for_new_devices_and_none_for_baseline_ecus(
    tmp_path: Path,
) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    s.capture._ingest(claim(0x8000FE003C04D2E8, 238, fc.mono()))  # E04, approved
    run(s, fc, 1.0, 0, 249, 238)
    run(s, fc, 31.0)
    recs = [r for r in records(tmp_path) if r["type"].startswith("connection_")]
    assert sorted((r["type"], r["sa"]) for r in recs) == [
        ("connection_end", 238), ("connection_end", 249),
        ("connection_start", 238), ("connection_start", 249),
    ]  # fmt: skip
    eld = next(r for r in recs if r["type"] == "connection_end" and r["sa"] == 238)
    assert eld["sev"] == "info" and "pgns_sent" not in eld  # approved: short form


def test_NP_15_ecu_nack_to_the_logger_is_not_a_new_pgn(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    assert s.logger_sa == 247
    nack = bytes([1, 0xFF, 0xFF, 0xFF, 247]) + (65259).to_bytes(3, "little")
    s.capture._ingest(frame((6 << 26) | (0xE8 << 16) | (0xFF << 8) | 0, nack, fc.mono()))
    run(s, fc, 0.5, 0)
    assert not [r for r in records(tmp_path) if r["type"] == "known_device_new_pgn"]
