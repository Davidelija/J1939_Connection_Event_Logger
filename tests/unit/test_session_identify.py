"""Step 5 in the session: classification, identification and final identification (PR 2)."""

from __future__ import annotations

import json
import shutil
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
SCAN = 0x8000810033A1B2C4  # function 129
TRAILER = 0x900400003E803039  # industry group 1, vehicle system 2 (classify.trailer_vehicle_system)


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


def make(root: Path, library: Optional[bytes] = None) -> tuple[Session, FakeClock]:
    folder = root / "card" / "library"
    folder.mkdir(parents=True)
    if library is None:
        shutil.copy(EXAMPLES / "lib-v1.json", folder / "lib-v1.json")
    else:
        (folder / "lib-v2.json").write_bytes(library)
    fc = FakeClock(start_utc=START, start_mono=100.0)
    versions = {"config": "cfg-v3", "inventory": "inv-v2", "library": None}
    return Session(Bus(clock=fc, root=root), settings(), inventory(), versions, None), fc


def frame(cid: int, data: bytes, t: float) -> Frame:
    return Frame(1.7e9 + t, t, cid, True, False, False, data, False)


def claim(name: int, sa: int, t: float) -> Frame:
    return frame(0x18EEFF00 | sa, name.to_bytes(8, "little"), t)


def request(pgn: int, sa: int, da: int, t: float) -> Frame:
    return frame((6 << 26) | (0xEA << 16) | (da << 8) | sa, pgn.to_bytes(3, "little"), t)


def run(s: Session, fc: FakeClock, seconds: float, *senders: int, step: float = 0.1) -> None:
    end = fc.mono() + seconds
    while fc.mono() < end:
        for sa in senders:
            s.capture._ingest(frame((6 << 26) | (61444 << 8) | sa, bytes(8), fc.mono()))
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


def requests_from(s: Session, fc: FakeClock, sa: int, pgns: list[int]) -> None:
    for pgn in pgns:
        s.capture._ingest(request(pgn, sa, 0, fc.mono()))
    run(s, fc, 0.2, 0, sa)


def test_IDN_4_session_identifies_the_scan_tool_when_its_identity_requests_finish(
    tmp_path: Path,
) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 0.5, 0, 249)
    requests_from(s, fc, 249, [65260, 65259, 65226, 65227])
    run(s, fc, 12.0, 0, 249)  # three identity requests, each tried twice (NP-14)
    recs = records(tmp_path)
    assert recs[0]["library"] == "lib-v1"  # IDN-5: the version in the header
    [ident] = [r for r in recs if r["type"] == "identification"]
    assert (ident["sa"], ident["sev"], ident["type_guess"]) == (
        249, "notice", "diagnostic tool, code reader",
    )  # fmt: skip
    assert ident["id_source"] == ["NAME", "request pattern"] and ident["confidence"] == "medium"
    assert [r["outcome"] for r in ident["requests"]] == ["no reply"] * 3


def test_IDN_4_connection_end_carries_the_final_identification_when_it_changes(
    tmp_path: Path,
) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 0.5, 0, 249)
    requests_from(s, fc, 249, [65260, 65259, 65226, 65227])
    run(s, fc, 12.0, 0, 249)
    requests_from(s, fc, 249, [65230, 65231, 65242, 64965])  # now a heavy-duty scan tool
    run(s, fc, 31.0)  # key-off
    [end] = [r for r in records(tmp_path) if r["type"] == "connection_end"]
    final = end["final_identification"]
    assert final["type_guess"] == "diagnostic tool, heavy-duty scan tool"
    assert final["make_source"] == "library" and final["profile_match"].startswith("matches")
    assert end["sev"] == "high"


def test_IDN_4_no_final_identification_when_nothing_changed(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 0.5, 0, 249)
    requests_from(s, fc, 249, [65260, 65259, 65226, 65227])
    run(s, fc, 12.0, 0, 249)
    run(s, fc, 31.0)
    [end] = [r for r in records(tmp_path) if r["type"] == "connection_end"]
    assert "final_identification" not in end


def test_DET_18_trailer_that_sends_requests_is_reclassified_high(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(TRAILER, 200, fc.mono()))
    run(s, fc, 0.5, 0, 200)
    requests_from(s, fc, 200, [65226])  # a diagnostic request
    run(s, fc, 12.0, 0, 200)
    run(s, fc, 31.0)
    recs = records(tmp_path)
    [start] = [r for r in recs if r["type"] == "connection_start"]
    assert (start["category"], start["sev"], start["classification_rule"]) == (
        "trailer device", "notice", "NAME",
    )  # fmt: skip
    [ident] = [r for r in recs if r["type"] == "identification"]
    assert (ident["category"], ident["classification_rule"]) == (
        "external device (unrecognized)", "request activity",
    )  # fmt: skip
    assert ident["reclassified"] == "sent a diagnostic request (PGN 65226)"
    [end] = [r for r in recs if r["type"] == "connection_end"]
    assert end["sev"] == "high"  # the final severity (DC-17)


def test_DET_18_broadcast_only_trailer_stays_a_trailer_at_notice(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(TRAILER, 200, fc.mono()))
    run(s, fc, 12.5, 0, 200)
    run(s, fc, 31.0)
    recs = records(tmp_path)
    [ident] = [r for r in recs if r["type"] == "identification"]
    assert ident["category"] == "trailer device" and ident["reclassified"] is None
    [end] = [r for r in recs if r["type"] == "connection_end"]
    assert end["sev"] == "notice"


def test_IDN_5_corrupt_library_is_a_high_fault_and_identification_continues(
    tmp_path: Path,
) -> None:
    s, fc = make(tmp_path, library=b'{"format": "lib-1", "library": "lib-v2", "devices": 3}')
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 0.5, 0, 249)
    requests_from(s, fc, 249, [65260, 65259, 65226, 65227])
    run(s, fc, 12.0, 0, 249)
    recs = records(tmp_path)
    [fault] = [r for r in recs if r["type"] == "fault" and "library" in r["cause"]]
    assert fault["sev"] == "high" and fault["logger_action"] == "identifying without it"
    assert fault["cause"].startswith("device library corrupt")
    [ident] = [r for r in recs if r["type"] == "identification"]
    assert ident["type_guess"] is None and ident["confidence"] == "low"  # DC-19
    assert recs[0]["library"] is None


def test_SC_3_a_device_is_detected_and_identified_from_message_content(tmp_path: Path) -> None:
    s, fc = make(tmp_path)
    started(s, fc)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 0.5, 0, 249)
    requests_from(s, fc, 249, [65260, 65259, 65226, 65227, 65235])
    run(s, fc, 12.0, 0, 249)
    run(s, fc, 31.0)
    types = [r["type"] for r in records(tmp_path)]
    for t in ("connection_start", "control_flag", "identification", "connection_end"):
        assert t in types, t
    assert types.index("connection_start") < types.index("identification")
    assert types.index("identification") < types.index("connection_end")
