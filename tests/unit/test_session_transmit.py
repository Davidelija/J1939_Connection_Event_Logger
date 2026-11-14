"""Step 3 in the session: bit rate, claim, requests, guard, VIN check, witness checks."""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

import pytest

from j1939logger.detect import InventoryEntry
from j1939logger.main import inventory_from_file
from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.session import Session, session_files, settings_from_config
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
NAME = 0x9FFEFFFFFFE00001
ENGINE = 0x000000002E412A10
SCAN = 0x8000810033A1B2C4
VIN = "1XKYD49X0GJ123456"
ALLOWED_PGNS = {59904, 60928, 59392, 60416}
ALLOWED_REQUESTS = {60928, 65254, 65260, 65259, 65242, 64965}
_FRAME = struct.Struct("=IB3x8s")


class RecordingSocket:
    """A CAN socket that records what the logger sends (the witness's view)."""

    def __init__(self, clock: FakeClock, sent: list[tuple[float, int, bytes]]) -> None:
        self.clock = clock
        self.sent = sent

    def setsockopt(self, *a: Any) -> None: ...
    def getsockopt(self, *a: Any) -> int:
        return 1 << 20

    def settimeout(self, t: float) -> None: ...
    def recvmsg(self, *a: Any) -> Any:
        time.sleep(0.005)
        raise socket.timeout()

    def send(self, data: bytes) -> int:
        cid, dlc, payload = _FRAME.unpack(data)
        self.sent.append((self.clock.mono(), cid & 0x1FFFFFFF, payload[:dlc]))
        return len(data)

    def close(self) -> None: ...


class Bus(DesktopPlatform):
    def __init__(
        self, sent: list[tuple[float, int, bytes]], rate: Optional[int] = 250000, **kw: Any
    ) -> None:
        super().__init__(**kw)
        self.sent = sent
        self.rate = rate

    def open_can(self, listen_only: bool) -> socket.socket:
        assert self._fake is not None
        return cast(socket.socket, RecordingSocket(self._fake, self.sent))

    def bitrate_check(self) -> Optional[int]:
        return self.rate


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def inventory() -> dict[int, InventoryEntry]:
    return inventory_from_file(json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8")))


def make(
    root: Path,
    rate: Optional[int] = 250000,
    plan: Sequence[FaultSpec] = (),
    fc: Optional[FakeClock] = None,
) -> tuple[Session, FakeClock, list[tuple[float, int, bytes]]]:
    fc = fc or FakeClock(start_utc=START, start_mono=100.0)
    sent: list[tuple[float, int, bytes]] = []
    p = Bus(sent, rate, fault_plan=plan, clock=fc, root=root)
    versions = {"config": "cfg-v3", "inventory": "inv-v2", "library": "lib-v1"}
    s = Session(p, settings(), inventory(), versions, None, (0, 3, 11, 238), VIN)
    return s, fc, sent


def frame(cid: int, data: bytes, t: float, error: bool = False) -> Frame:
    return Frame(1.7e9 + t, t, cid, not error, False, error, data, False)


def eec1(t: float) -> Frame:
    return frame(0x0CF00400, bytes(8), t)


def run(
    s: Session, fc: FakeClock, seconds: float, step: float = 0.05, traffic: bool = True
) -> None:
    end = fc.mono() + seconds
    while fc.mono() < end:
        if traffic:
            s.capture._ingest(eec1(fc.mono()))
        s.step()
        fc.advance(step)


def records(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in session_files(root / "card" / "sessions"):
        out += [json.loads(x) for x in f.path.read_text("utf-8").splitlines()]
    return out


def stop(s: Session) -> None:
    s.stop()
    s.run()


def pgn_of(cid: int) -> int:
    pf = (cid >> 16) & 0xFF
    return ((cid >> 8) & 0xFFFF) if pf >= 240 else (pf << 8)


def witness(sent: list[tuple[float, int, bytes]]) -> None:
    """The witness checks (test plan section 3): allow-list and 10 frames/s."""
    times = [t for t, _, _ in sent]
    for t in times:
        assert sum(1 for u in times if t <= u < t + 1.0) <= 10
    for _, cid, data in sent:
        pgn = (cid >> 8) & 0x3FF00 if ((cid >> 16) & 0xFF) < 240 else (cid >> 8) & 0x3FFFF
        assert pgn in ALLOWED_PGNS, hex(cid)
        if pgn == 59904:
            assert int.from_bytes(data[:3], "little") in ALLOWED_REQUESTS
        if pgn == 60928:
            assert data == NAME.to_bytes(8, "little")
        assert cid & 0xFF in (247, 246, 254)


def bam_frames(sa: int, pgn: int, payload: bytes, t: float) -> list[Frame]:
    packets = (len(payload) + 6) // 7
    cm = bytes([32, len(payload), 0, packets, 0xFF]) + pgn.to_bytes(3, "little")
    out = [frame((7 << 26) | (0xEC << 16) | (0xFF << 8) | sa, cm, t)]
    for i in range(packets):
        chunk = payload[i * 7 : i * 7 + 7].ljust(7, b"\xff")
        out.append(
            frame(
                (7 << 26) | (0xEB << 16) | (0xFF << 8) | sa,
                bytes([i + 1]) + chunk,
                t + 0.05 * (i + 1),
            )
        )
    return out


# -- start-up --------------------------------------------------------------------------


def test_NP_1_claim_first_then_header_with_the_claim_result_then_requests(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 1.0)
    stop(s)
    _, first_id, first_data = sent[0]
    assert first_id == 0x18EEFFF7 and first_data == NAME.to_bytes(8, "little")  # the claim
    later = [t for t, cid, _ in sent[1:]]
    assert later and min(later) - sent[0][0] >= 0.25  # NP-6
    header = records(tmp_path)[0]
    assert (header["logger_sa"], header["logger_claim"], header["bitrate"]) == (
        247,
        "ok after 250 ms",
        250000,
    )
    assert (header["vin_status"], header["restart_guard"]) == ("pending", "not triggered")
    asked = sorted(int.from_bytes(d[:3], "little") for _, cid, d in sent if pgn_of(cid) == 59904)
    assert asked == [60928, 65254]  # sweep and Time/Date first; VIN waits its turn at SA 0
    witness(sent)


def test_NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s(
    tmp_path: Path,
) -> None:
    s, fc, sent = make(tmp_path, rate=None)
    s.start()
    run(s, fc, 61.0, step=0.5)
    stop(s)
    assert sent == []
    r = records(tmp_path)
    assert (r[0]["bitrate"], r[0]["logger_claim"]) == (None, "not claimed (bit rate not confirmed)")
    faults = [x for x in r if x["type"] == "fault"]
    assert [f["sev"] for f in faults] == ["high"] and "no bit rate" in faults[0]["cause"]


def test_NP_19_restart_loop_starts_listen_only_with_a_high_fault(tmp_path: Path) -> None:
    s, fc, _ = make(tmp_path)
    s.start()
    run(s, fc, 1.0)
    s.capture.stop()  # unclean end of session 1
    assert s.eventlog is not None
    s.eventlog.close()
    st_path = tmp_path / "flash" / "state.json"
    st = json.loads(st_path.read_text())
    st["unclean_starts"] = ["2026-11-06T14:02:00.000Z", "2026-11-06T14:02:05.000Z"]
    st_path.write_text(json.dumps(st))
    s2, _, sent2 = make(tmp_path, fc=fc)
    s2.start()
    run(s2, fc, 2.0)
    stop(s2)
    assert sent2 == []
    second = records(tmp_path)
    header2 = [x for x in records(tmp_path) if x["type"] == "session_start" and x["session"] == 2][
        0
    ]
    assert header2["restart_guard"] == "triggered; transmit disabled"
    assert any(
        x["type"] == "fault" and x["cause"] == "restart loop; transmit disabled" for x in second
    )
    assert json.loads(st_path.read_text())["unclean_starts"] == []  # cleared by the clean end


def test_NP_2_channel_switches_to_normal_mode_after_the_bit_rate_is_confirmed(
    tmp_path: Path,
) -> None:
    s, fc, _ = make(tmp_path, rate=None)
    s.start()
    assert s.capture.listen_only is True
    s.capture._platform.rate = 500000  # type: ignore[attr-defined]
    run(s, fc, 0.5)
    assert s.capture.listen_only is False
    stop(s)


# -- while running --------------------------------------------------------------------


def test_NP_3_bus_off_turns_transmit_off_for_the_session(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 1.0)
    before = len(sent)
    s.capture._ingest(frame(0x40, bytes(8), fc.mono(), error=True))
    run(s, fc, 5.0)
    stop(s)
    assert len(sent) == before
    r = records(tmp_path)
    assert any(x["type"] == "fault" and "bus_off" in x["cause"] for x in r)
    assert r[-1]["bus_off"] is True


def test_NP_7_contest_at_247_concedes_and_claims_246(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 1.0)
    s.capture._ingest(frame(0x18EEFFF7, (ENGINE + 99).to_bytes(8, "little"), fc.mono()))
    run(s, fc, 1.0)
    stop(s)
    claims = [cid & 0xFF for _, cid, _ in sent if pgn_of(cid) == 60928]
    assert claims[:2] == [247, 246]
    assert any(x["type"] == "address_conflict" for x in records(tmp_path))
    witness(sent)


def test_NP_8_request_to_the_logger_is_nacked(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 1.0)
    s.capture._ingest(frame(0x18EAF7F9, (65260).to_bytes(3, "little"), fc.mono()))
    run(s, fc, 0.5)
    stop(s)
    nacks = [(cid, d) for _, cid, d in sent if pgn_of(cid) == 59392]
    assert nacks and nacks[0][1][0] == 1 and nacks[0][1][4] == 0xF9


def test_NP_12_vin_reply_gives_vin_check_match(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 1.0)  # Time/Date asked; no reply, so VIN follows after the retry
    run(s, fc, 2.5)
    for f in bam_frames(0x00, 65260, (VIN + "*").encode(), fc.mono()):
        s.capture._ingest(f)
    run(s, fc, 1.0)
    stop(s)
    [check] = [x for x in records(tmp_path) if x["type"] == "vin_check"]
    assert (check["vin"], check["vin_status"], check["outcome"]) == (VIN, "match", "reply")


def test_NP_14_no_vin_reply_gives_vin_check_unavailable(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 8.0)
    stop(s)
    [check] = [x for x in records(tmp_path) if x["type"] == "vin_check"]
    assert (check["vin"], check["vin_status"], check["outcome"]) == (
        None,
        "unavailable",
        "no reply",
    )


def test_NP_13_new_device_is_asked_for_its_identity(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 15.0)  # past the wake window
    s.capture._ingest(frame(0x18EEFFF9, SCAN.to_bytes(8, "little"), fc.mono()))
    run(s, fc, 5.0)
    stop(s)
    to_scan = [
        int.from_bytes(d[:3], "little")
        for _, cid, d in sent
        if pgn_of(cid) == 59904 and (cid >> 8) & 0xFF == 0xF9
    ]
    assert to_scan[:1] == [65259]
    witness(sent)


def test_NP_9_rts_to_the_logger_gets_cts(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    run(s, fc, 1.0)
    rts = bytes([16, 20, 0, 3, 0xFF]) + (65259).to_bytes(3, "little")
    s.capture._ingest(frame((7 << 26) | (0xEC << 16) | (0xF7 << 8) | 0x00, rts, fc.mono()))
    run(s, fc, 0.2)
    stop(s)
    cts = [d for _, cid, d in sent if pgn_of(cid) == 60416]
    assert cts and cts[0][0] == 17


def test_NP_16_witness_over_a_busy_minute(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path)
    s.start()
    for i in range(10):  # ten new devices join at once
        name = (SCAN + i).to_bytes(8, "little")
        s.capture._ingest(frame(0x18EEFF00 | (0x80 + i), name, fc.mono()))
    run(s, fc, 60.0)
    stop(s)
    assert len(sent) > 20
    witness(sent)
    end = records(tmp_path)[-1]
    assert end["logger_tx"]["claims"] == 1 and end["logger_tx"]["requests"] == len(
        [1 for _, cid, _ in sent if pgn_of(cid) == 59904]
    )


def test_NP_18_send_error_turns_transmit_off_with_a_high_fault(tmp_path: Path) -> None:
    s, fc, sent = make(tmp_path, plan=[(100.5, "enobufs", None)])
    s.start()
    run(s, fc, 3.0)
    stop(s)
    assert any(
        x["type"] == "fault" and "enobufs" in x["cause"] and x["sev"] == "high"
        for x in records(tmp_path)
    )


# -- the witness on vcan0 ------------------------------------------------------------------

_VCAN = sys.platform.startswith("linux") and os.path.exists("/sys/class/net/vcan0")
needs_vcan = pytest.mark.skipif(not _VCAN, reason="needs Linux with vcan0 up (CI loads it)")


@needs_vcan
def test_NP_9_witness_on_vcan0_sees_only_allowed_frames_within_the_rate_cap(tmp_path: Path) -> None:
    watch = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    watch.bind(("vcan0",))
    watch.settimeout(0.05)
    platform = DesktopPlatform(interface="vcan0", root=tmp_path)
    s = Session(platform, settings(), inventory(), None, None, (0, 3, 11, 238), VIN)
    s.start()
    runner = threading.Thread(target=s.run, daemon=True)
    runner.start()
    seen: list[tuple[float, int, bytes]] = []
    end = time.monotonic() + 3.0
    try:
        while time.monotonic() < end:
            try:
                cid, dlc, data = _FRAME.unpack(watch.recv(16))
            except socket.timeout:
                continue
            if (cid & 0xFF) in (247, 246, 254):
                seen.append((time.monotonic(), cid & 0x1FFFFFFF, data[:dlc]))
    finally:
        s.stop()
        runner.join(timeout=3)
        watch.close()
    assert seen and seen[0][1] == 0x18EEFFF7  # the claim comes first
    witness(seen)
