"""Step 1 gate (DC-9): a new claim gives a chained connection_start within 2 s.

The in-process test feeds frames into capture's queue; the vcan0 test sends a
real claim on the bus and measures the time to the synced record.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from j1939logger.config import Inventory
from j1939logger.eventlog import ZERO_HASH, record_hash
from j1939logger.main import inventory_from_file
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import Session, settings_from_config
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
SCAN_TOOL = 0x8000810033A1B2C4
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def inventory() -> Inventory:
    return inventory_from_file(json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8")))


def records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def verify_chain(recs: list[dict[str, Any]], prev: str) -> None:
    for r in recs:
        assert r["prev"] == prev
        prev_hash = record_hash(prev, {k: v for k, v in r.items() if k != "hash"})
        assert prev_hash == r["hash"]
        prev = r["hash"]


class _IdleSocket:
    def setsockopt(self, *a: Any) -> None: ...
    def getsockopt(self, *a: Any) -> int:
        return 1 << 20

    def settimeout(self, t: float) -> None: ...
    def recvmsg(self, *a: Any) -> Any:
        time.sleep(0.005)  # like a real socket timeout, without spinning the CPU
        raise socket.timeout()

    def send(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None: ...


class _NoBusPlatform(DesktopPlatform):
    def open_can(self, listen_only: bool) -> socket.socket:
        return cast(socket.socket, _IdleSocket())


def test_DET_1_settings_and_inventory_come_from_the_config_files() -> None:
    s = settings()
    assert s["limits.tp_sessions"] == 32 and s["classify.wake_window_s"] == 10
    inv = inventory()
    assert inv.by_name()[0x8000FE003C04D2E8].entry == "E04"
    with pytest.raises(ValueError):
        settings_from_config({"can": {}})


def test_DET_16_new_claim_gives_synced_chained_connection_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    session = Session(_NoBusPlatform(clock=fc, root=tmp_path), settings(), inventory())
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    session.start()
    try:
        eec1 = Frame(1.0, 100.0, 0x0CF00400, True, False, False, bytes(8), False)
        claim = Frame(
            2.0, 160.0, 0x18EEFFF9, True, False, False, SCAN_TOOL.to_bytes(8, "little"), False
        )
        session.capture._ingest(eec1)
        session.capture._ingest(claim)
        fc.advance(60.5)
        assert session.step() == 2
    finally:
        session.capture.stop()
    assert session.eventlog is not None
    all_recs = records(session.eventlog.path)
    assert all_recs[0]["type"] == "session_start"
    [rec] = [r for r in all_recs if r["type"] == "connection_start"]
    assert (rec["type"], rec["sev"], rec["conn"], rec["sa"]) == (
        "connection_start",
        "high",
        1,
        0xF9,
    )
    assert rec["category"] == "external device (unrecognized)"
    verify_chain(all_recs, ZERO_HASH)
    assert synced, "connection_start was not synced at once"
    written = datetime.fromisoformat(rec["written"].replace("Z", "+00:00"))
    utc = datetime.fromisoformat(rec["utc"].replace("Z", "+00:00"))
    assert 0 <= (written - utc).total_seconds() <= 2.0


_VCAN = sys.platform.startswith("linux") and os.path.exists("/sys/class/net/vcan0")
needs_vcan = pytest.mark.skipif(not _VCAN, reason="needs Linux with vcan0 up (CI loads it)")


@needs_vcan
def test_DET_16_connection_start_within_2_s_on_vcan0(tmp_path: Path) -> None:
    platform = DesktopPlatform(interface="vcan0", root=tmp_path)
    session = Session(platform, settings(), inventory())
    session.start()
    runner = threading.Thread(target=session.run, daemon=True)
    runner.start()
    tx = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        tx.bind(("vcan0",))
        frame = struct.pack("=IB3x8s", 0x18EEFFF9 | 0x80000000, 8, SCAN_TOOL.to_bytes(8, "little"))
        sent = time.monotonic()
        tx.send(frame)
        assert session.eventlog is not None
        path = session.eventlog.path
        recs: list[dict[str, Any]] = []
        while time.monotonic() - sent < 2.0:
            if path.exists() and path.read_bytes().endswith(b"\n"):
                recs = [r for r in records(path) if r["type"] == "connection_start"]
                if recs:
                    break
            time.sleep(0.01)
        elapsed = time.monotonic() - sent
    finally:
        tx.close()
        session.stop()
        runner.join(timeout=3)
    assert recs, f"no connection_start within 2 s ({elapsed:.2f} s)"
    assert recs[0]["type"] == "connection_start" and recs[0]["sa"] == 0xF9
    assert elapsed <= 2.0
    verify_chain(records(path), ZERO_HASH)
