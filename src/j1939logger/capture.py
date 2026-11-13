"""capture: frames in, timestamped records out (docs/modules.md section 4, contract v1).

Layer 1; the only receiver on the CAN bus (CLAUDE.md rule 6). A thread reads
the raw SocketCAN socket from ``platform.open_can()`` with ``recvmsg`` and
puts each frame in two places: a pending queue that the main loop drains
with ``read_batch()``, and a ring of the last ``logging.raw_before_s`` + 2
seconds that ``rawcap`` reads with ``window()``.

* Receive buffer: set from ``can.rx_buffer_bytes`` with ``SO_RCVBUFFORCE``
  (``SO_RCVBUF`` if not permitted) and read back (DC-6, LOG-15).
* Timestamps: ``Frame.ts_kernel`` is the kernel receive time (``SO_TIMESTAMP``);
  ``Frame.ts_mono`` is that time converted to monotonic time with the wall
  minus monotonic difference sampled from the platform at read time, so a
  frame read late keeps its receive time. If the platform has no wall time
  (real-time clock invalid), ``ts_mono`` is the monotonic time of the read.
* Own frames (sent by this logger, ``MSG_CONFIRM``) are marked ``Frame.own``.
* Kernel drops: the ``SO_RXQ_OVFL`` count from the latest frame's ancillary data.
* Mode change: ``set_mode()`` closes the socket and opens it again (DC-6).
* Errors: a ``PlatformError`` (or an OS error, as ``can_down``) stops the
  thread; ``read_batch()`` raises it once the pending frames are drained.
  Capture never raises on frame content and never syncs files.
"""

from __future__ import annotations

import errno
import socket
import struct
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from j1939logger.platform.interface import Platform
from j1939logger.types import Frame, PlatformError

__all__ = ["Capture", "CaptureStats", "parse_frame"]

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x000007FF
MSG_CONFIRM = 0x800

_FRAME = struct.Struct("=IB3x8s")  # struct can_frame
_TIMEVAL = struct.Struct("=qq")  # struct timeval on 64-bit Linux
_U32 = struct.Struct("=I")
_SO_TIMESTAMP = getattr(socket, "SO_TIMESTAMP", 29)
_SO_RXQ_OVFL = getattr(socket, "SO_RXQ_OVFL", 40)
_SO_RCVBUFFORCE = getattr(socket, "SO_RCVBUFFORCE", 33)
# CMSG_SPACE exists only on Unix; the value is used only where AF_CAN exists.
_ANC_SIZE = (
    socket.CMSG_SPACE(_TIMEVAL.size) + socket.CMSG_SPACE(_U32.size)
    if hasattr(socket, "CMSG_SPACE")
    else 64
)
_READ_TIMEOUT_S = 0.2


@dataclass
class CaptureStats:
    """Capture counts (DC-8)."""

    kernel_drops: int = 0
    rx_buffer_bytes: int = 0
    frames: dict[str, int] = field(
        default_factory=lambda: {"extended": 0, "standard": 0, "remote": 0, "error": 0}
    )


def parse_frame(
    raw: bytes,
    ancdata: list[tuple[int, int, bytes]],
    flags: int,
    wall_minus_mono: Optional[float],
    read_mono: float,
) -> tuple[Frame, Optional[int]]:
    """One ``struct can_frame`` and its ancillary data -> (Frame, kernel drop count or None)."""
    can_id, dlc, payload = _FRAME.unpack(raw[: _FRAME.size].ljust(_FRAME.size, b"\0"))
    ts_kernel: Optional[float] = None
    drops: Optional[int] = None
    for level, kind, data in ancdata:
        if level != socket.SOL_SOCKET:
            continue
        if kind == _SO_TIMESTAMP and len(data) >= _TIMEVAL.size:
            sec, usec = _TIMEVAL.unpack(data[: _TIMEVAL.size])
            ts_kernel = sec + usec / 1e6
        elif kind == _SO_RXQ_OVFL and len(data) >= _U32.size:
            drops = _U32.unpack(data[: _U32.size])[0]
    if ts_kernel is not None and wall_minus_mono is not None:
        ts_mono = ts_kernel - wall_minus_mono
    else:
        ts_mono = read_mono
        if ts_kernel is None:
            ts_kernel = read_mono if wall_minus_mono is None else read_mono + wall_minus_mono
    extended = bool(can_id & CAN_EFF_FLAG)
    frame = Frame(
        ts_kernel=ts_kernel,
        ts_mono=ts_mono,
        can_id=can_id & (CAN_EFF_MASK if extended else CAN_SFF_MASK),
        extended=extended,
        remote=bool(can_id & CAN_RTR_FLAG),
        error=bool(can_id & CAN_ERR_FLAG),
        data=bytes(payload[: min(dlc, 8)]),
        own=bool(flags & MSG_CONFIRM),
    )
    return frame, drops


def _kind(f: Frame) -> str:
    if f.error:
        return "error"
    if f.remote:
        return "remote"
    return "extended" if f.extended else "standard"


class Capture:
    """The only CAN receiver."""

    def __init__(self, platform: Platform, rx_buffer_bytes: int, raw_before_s: float) -> None:
        self._platform = platform
        self._rx_buffer_bytes = rx_buffer_bytes
        self._ring_s = raw_before_s + 2.0
        self._lock = threading.Lock()
        self._pending: deque[Frame] = deque()
        self._ring: deque[Frame] = deque()
        self._stats = CaptureStats()
        self._error: Optional[PlatformError] = None
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.listen_only: Optional[bool] = None

    # -- lifecycle ------------------------------------------------------------

    def start(self, listen_only: bool) -> None:
        """Open the socket and start the receive thread. Raises PlatformError."""
        sock = self._platform.open_can(listen_only)
        self._stats.rx_buffer_bytes = self._set_buffer(sock)
        sock.settimeout(_READ_TIMEOUT_S)
        self._sock = sock
        self.listen_only = listen_only
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def set_mode(self, listen_only: bool) -> None:
        """Switch listen-only/normal by closing the socket and opening it again (DC-6)."""
        self.stop()
        self.start(listen_only)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _set_buffer(self, sock: socket.socket) -> int:
        try:
            sock.setsockopt(socket.SOL_SOCKET, _SO_RCVBUFFORCE, self._rx_buffer_bytes)
        except OSError:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self._rx_buffer_bytes)
            except OSError:
                pass
        return int(sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF))

    # -- receive thread -------------------------------------------------------

    def _wall_minus_mono(self) -> tuple[Optional[float], float]:
        r = self._platform.now()
        if r.wall_utc is None:
            return None, r.mono
        return r.wall_utc.timestamp() - r.mono, r.mono

    def _run(self) -> None:
        sock: Any = self._sock
        while not self._stop.is_set():
            try:
                self._platform.fault("can_recv")
                raw, anc, flags, _ = sock.recvmsg(_FRAME.size, _ANC_SIZE)
            except socket.timeout:
                continue
            except PlatformError as exc:
                self._fail(exc)
                return
            except OSError as exc:
                if self._stop.is_set():
                    return
                self._fail(PlatformError("can_down", errno.errorcode.get(exc.errno or 0, str(exc))))
                return
            wmm, mono = self._wall_minus_mono()
            frame, drops = parse_frame(raw, anc, flags, wmm, mono)
            self._ingest(frame, drops)

    def _fail(self, exc: PlatformError) -> None:
        with self._lock:
            self._error = exc

    def _ingest(self, frame: Frame, drops: Optional[int] = None) -> None:
        with self._lock:
            self._pending.append(frame)
            self._ring.append(frame)
            cutoff = frame.ts_mono - self._ring_s
            while self._ring and self._ring[0].ts_mono < cutoff:
                self._ring.popleft()
            kind = _kind(frame)
            self._stats.frames[kind] = self._stats.frames.get(kind, 0) + 1
            if drops is not None:
                self._stats.kernel_drops = drops

    # -- outputs --------------------------------------------------------------

    def read_batch(self, max_n: int) -> list[Frame]:
        """Frames already received, up to ``max_n``, oldest first; never waits (DC-8)."""
        with self._lock:
            n = min(max_n, len(self._pending))
            batch = [self._pending.popleft() for _ in range(n)]
            if not batch and self._error is not None:
                exc, self._error = self._error, None
                raise exc
            return batch

    def window(self, start_mono: float, end_mono: float) -> list[Frame]:
        """Frames in the ring with start_mono <= ts_mono <= end_mono (DC-8)."""
        with self._lock:
            return [f for f in self._ring if start_mono <= f.ts_mono <= end_mono]

    def stats(self) -> CaptureStats:
        with self._lock:
            return CaptureStats(
                kernel_drops=self._stats.kernel_drops,
                rx_buffer_bytes=self._stats.rx_buffer_bytes,
                frames=dict(self._stats.frames),
            )
