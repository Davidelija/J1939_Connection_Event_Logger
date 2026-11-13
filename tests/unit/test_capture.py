"""capture: frame parsing, kernel timestamps, the ring, stats and errors."""

from __future__ import annotations

import errno
import os
import socket
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from j1939logger.capture import (
    CAN_EFF_FLAG,
    CAN_ERR_FLAG,
    CAN_RTR_FLAG,
    MSG_CONFIRM,
    Capture,
    parse_frame,
)
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.types import Frame, PlatformError

SOL = socket.SOL_SOCKET
TS, OVFL = 29, 40  # SO_TIMESTAMP, SO_RXQ_OVFL on Linux
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


def raw(can_id: int, data: bytes) -> bytes:
    return struct.pack("=IB3x8s", can_id, len(data), data.ljust(8, b"\0"))


def tv(t: float) -> bytes:
    return struct.pack("=qq", int(t), int(round((t % 1) * 1e6)))


def frame(t: float) -> Frame:
    return Frame(t + 1e9, t, 0x0CF00400, True, False, False, bytes(8), False)


# -- parsing ------------------------------------------------------------------


def test_LOG_15_parse_frame_reads_drop_count_and_flags() -> None:
    f, drops = parse_frame(
        raw(0x0CF00400 | CAN_EFF_FLAG, b"\x01\x02"),
        [(SOL, OVFL, struct.pack("=I", 7))],
        0,
        None,
        5.0,
    )
    assert drops == 7
    assert (f.can_id, f.extended, f.remote, f.error, f.data, f.own) == (
        0x0CF00400,
        True,
        False,
        False,
        b"\x01\x02",
        False,
    )


def test_LOG_15_parse_frame_types_and_own() -> None:
    std, _ = parse_frame(raw(0x123, b""), [], 0, None, 0.0)
    rtr, _ = parse_frame(raw(0x18FEF100 | CAN_EFF_FLAG | CAN_RTR_FLAG, b""), [], 0, None, 0.0)
    err, _ = parse_frame(raw(0x4 | CAN_ERR_FLAG, bytes(8)), [], 0, None, 0.0)
    own, _ = parse_frame(
        raw(0x18EAFFFE | CAN_EFF_FLAG, b"\x00\xee\x00"), [], MSG_CONFIRM, None, 0.0
    )
    assert (std.extended, std.can_id) == (False, 0x123)
    assert rtr.remote and err.error and own.own


def test_LOG_15_ts_mono_is_kernel_time_not_read_time() -> None:
    # Received at wall 1000.0 when mono was 100.0, read 1.5 s late: ts_mono stays 100.0.
    wall_minus_mono = 900.0
    f, _ = parse_frame(
        raw(0x0CF00400 | CAN_EFF_FLAG, b""), [(SOL, TS, tv(1000.0))], 0, wall_minus_mono, 101.5
    )
    assert f.ts_kernel == pytest.approx(1000.0)
    assert f.ts_mono == pytest.approx(100.0)


def test_LOG_15_without_wall_time_ts_mono_is_read_time() -> None:
    f, _ = parse_frame(raw(0x0CF00400 | CAN_EFF_FLAG, b""), [(SOL, TS, tv(1000.0))], 0, None, 101.5)
    assert f.ts_mono == 101.5


# -- ring, batches and stats ------------------------------------------------------


def make(tmp_path: Path) -> Capture:
    p = DesktopPlatform(clock=FakeClock(start_utc=START), root=tmp_path)
    return Capture(p, rx_buffer_bytes=1 << 20, raw_before_s=10.0)


def test_LOG_10_ring_keeps_raw_before_s_plus_2_seconds(tmp_path: Path) -> None:
    cap = make(tmp_path)
    for t in range(0, 30):
        cap._ingest(frame(float(t)))
    kept = cap.window(0.0, 100.0)
    assert kept[0].ts_mono == 17.0 and kept[-1].ts_mono == 29.0  # 29 - 12 = 17


def test_LOG_10_window_includes_both_ends(tmp_path: Path) -> None:
    cap = make(tmp_path)
    for t in (1.0, 2.0, 3.0, 4.0):
        cap._ingest(frame(t))
    assert [f.ts_mono for f in cap.window(2.0, 3.0)] == [2.0, 3.0]


def test_SC_2_read_batch_never_waits_and_keeps_order(tmp_path: Path) -> None:
    cap = make(tmp_path)
    assert cap.read_batch(10) == []
    for t in (1.0, 2.0, 3.0):
        cap._ingest(frame(t))
    assert [f.ts_mono for f in cap.read_batch(2)] == [1.0, 2.0]
    assert [f.ts_mono for f in cap.read_batch(10)] == [3.0]
    assert len(cap.window(0.0, 10.0)) == 3  # the ring keeps them for rawcap


def test_LOG_15_stats_count_frames_by_type_and_drops(tmp_path: Path) -> None:
    cap = make(tmp_path)
    cap._ingest(frame(1.0))
    cap._ingest(Frame(1.0, 1.0, 0x123, False, False, False, b"", False))
    cap._ingest(Frame(1.0, 1.0, 0x1, True, True, False, b"", False), drops=3)
    cap._ingest(Frame(1.0, 1.0, 0x4, False, False, True, bytes(8), False))
    s = cap.stats()
    assert s.frames == {"extended": 1, "standard": 1, "remote": 1, "error": 1}
    assert s.kernel_drops == 3


# -- errors -------------------------------------------------------------------------


class _FakeSocket:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.closed = False

    def setsockopt(self, *a: Any) -> None:
        pass

    def getsockopt(self, *a: Any) -> int:
        return 2 << 20

    def settimeout(self, t: float) -> None:
        pass

    def recvmsg(self, *a: Any) -> Any:
        raise self.exc

    def close(self) -> None:
        self.closed = True


class _FakeCanPlatform(DesktopPlatform):
    def __init__(self, exc: BaseException, **kw: Any) -> None:
        super().__init__(**kw)
        self.sock = _FakeSocket(exc)

    def open_can(self, listen_only: bool) -> socket.socket:
        return cast(socket.socket, self.sock)


def _wait_error(cap: Capture) -> PlatformError:
    for _ in range(50):
        try:
            cap.read_batch(10)
        except PlatformError as exc:
            return exc
        time.sleep(0.02)
    raise AssertionError("no error raised")


def test_NP_17_interface_down_raises_can_down_from_read_batch(tmp_path: Path) -> None:
    p = _FakeCanPlatform(OSError(errno.ENETDOWN, "down"), root=tmp_path)
    cap = Capture(p, rx_buffer_bytes=1 << 20, raw_before_s=10.0)
    cap.start(listen_only=True)
    assert _wait_error(cap).kind == "can_down"
    assert cap.stats().rx_buffer_bytes == 2 << 20
    cap.stop()
    assert p.sock.closed


def test_NP_17_can_down_fault_plan_reaches_read_batch(tmp_path: Path) -> None:
    p = _FakeCanPlatform(
        socket.timeout(), fault_plan=[(0.0, "can_down", None)], clock=FakeClock(), root=tmp_path
    )
    cap = Capture(p, rx_buffer_bytes=1 << 20, raw_before_s=10.0)
    cap.start(listen_only=True)
    assert _wait_error(cap).kind == "can_down"
    cap.stop()


def test_NP_17_missing_interface_raises_can_missing_on_start(tmp_path: Path) -> None:
    p = DesktopPlatform(fault_plan=[(0.0, "can_missing", None)], clock=FakeClock(), root=tmp_path)
    with pytest.raises(PlatformError) as exc:
        Capture(p, 1 << 20, 10.0).start(listen_only=True)
    assert exc.value.kind == "can_missing"


# -- vcan0 --------------------------------------------------------------------------

_VCAN = sys.platform.startswith("linux") and os.path.exists("/sys/class/net/vcan0")
needs_vcan = pytest.mark.skipif(not _VCAN, reason="needs Linux with vcan0 up (CI loads it)")


@needs_vcan
def test_LOG_15_capture_on_vcan0_timestamps_frames_and_reads_buffer_back(tmp_path: Path) -> None:
    p = DesktopPlatform(root=tmp_path)
    cap = Capture(p, rx_buffer_bytes=1 << 20, raw_before_s=10.0)
    cap.start(listen_only=True)
    tx = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        tx.bind(("vcan0",))
        before = p.now().mono
        tx.send(raw(0x18EEFFF9 | CAN_EFF_FLAG, bytes(range(8))))
        got: list[Frame] = []
        for _ in range(100):
            got += cap.read_batch(10)
            if got:
                break
            time.sleep(0.01)
        assert got and got[0].can_id == 0x18EEFFF9 and got[0].extended
        assert before - 0.5 <= got[0].ts_mono <= p.now().mono + 0.5
        assert cap.stats().rx_buffer_bytes > 0
        assert cap.listen_only is True
        cap.set_mode(listen_only=False)
        assert cap.listen_only is False
    finally:
        tx.close()
        cap.stop()
