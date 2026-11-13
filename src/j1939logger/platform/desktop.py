"""Desktop platform: the ``vcan0`` implementation used by every test.

``DesktopPlatform(fault_plan=[(at_mono, kind, args), ...], clock=FakeClock())``
is the test seam for the platform contract (docs/modules.md section 4):

* ``clock`` controls time. With a ``FakeClock`` the test moves time with
  ``advance(s)`` (monotonic and wall time together) and ``jump(s)`` (wall time
  only; timers on the monotonic clock do not move). With no clock the
  platform reads the host's clocks.
* ``fault_plan`` injects faults by kind, spelled as in the Kind column of
  docs/errors.md. Each entry is ``(at_mono, kind, args)`` with ``args`` a
  mapping or None.

Fault delivery (docs/design-changes.md, DC-5):

* ``can_missing``: ``open_can()`` raises ``PlatformError("can_missing")``.
* ``no_bitrate``: ``bitrate_check()`` returns None.
* ``rtc_invalid``: ``rtc_ok()`` returns False and ``now()`` reports no valid
  wall time (source ``elapsed``).

  These three are active from ``at_mono`` for ``args["for_s"]`` seconds, or
  for the rest of the run when ``for_s`` is not given.
* ``clock_jump``: the ``FakeClock``'s wall time jumps by ``args["s"]``
  seconds when its monotonic time reaches ``at_mono``. Needs a ``FakeClock``.
* Socket and storage errors, through ``fault(op)``, which layer 1 modules call
  just before each operation in ``FAULT_OPS``. While the fault is active,
  ``fault(op)`` raises ``PlatformError(kind)`` for the operations below
  (``args["ops"]`` narrows them):

  ==================  =================================
  kind                operations
  ==================  =================================
  ``can_down``        ``can_recv``, ``can_send``
  ``enobufs``         ``can_send``
  ``enospc``          ``card_write``
  ``erofs``           ``card_write``
  ``eio``             ``card_write``, ``card_sync``
  ``card_removed``    ``card_write``, ``card_sync``
  ``state_unwritable`` ``flash_write``
  ``slow_sync``       ``card_sync`` (delays by ``args["s"]`` seconds instead of raising)
  ==================  =================================

  These are active from ``at_mono`` for ``args["for_s"]`` seconds, or for the
  rest of the run, like the three above.

The other kinds in docs/errors.md are bus traffic, file contents, service
events or laptop-side conditions, not platform faults; DC-5 leaves how they
are injected open. A plan naming one of them raises ``NotImplementedError``
when it is built, so a test never believes a fault was injected when it was
not. An unknown kind raises ``ValueError``.

Hardware notes for ``vcan0``: listen-only mode is a no-op (hand-off, open
checks) and there is no bit rate, so ``bitrate_check()`` returns the
``bitrate`` given to the constructor (default 250000).
"""

from __future__ import annotations

import socket
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.platform.interface import FAULT_KINDS, FAULT_OPS, LIGHT_PATTERNS, Paths
from j1939logger.types import ClockReading, PlatformError

__all__ = ["DesktopPlatform", "FakeClock", "FaultSpec", "DELIVERED_FAULT_KINDS", "OPS_BY_KIND"]

FaultSpec = tuple[float, str, Optional[Mapping[str, Any]]]

# fault(op) kinds and the operations each one hits (module docstring, DC-5).
OPS_BY_KIND: dict[str, tuple[str, ...]] = {
    "can_down": ("can_recv", "can_send"),
    "enobufs": ("can_send",),
    "enospc": ("card_write",),
    "erofs": ("card_write",),
    "eio": ("card_write", "card_sync"),
    "card_removed": ("card_write", "card_sync"),
    "state_unwritable": ("flash_write",),
    "slow_sync": ("card_sync",),
}

# Kinds DesktopPlatform can inject (module docstring).
DELIVERED_FAULT_KINDS = ("can_missing", "no_bitrate", "rtc_invalid", "clock_jump") + tuple(
    OPS_BY_KIND
)

# Linux SocketCAN constants, by value where the socket module may not name them.
_SOL_CAN_RAW = getattr(socket, "SOL_CAN_RAW", 101)
_CAN_RAW_ERR_FILTER = getattr(socket, "CAN_RAW_ERR_FILTER", 2)
_CAN_RAW_RECV_OWN_MSGS = getattr(socket, "CAN_RAW_RECV_OWN_MSGS", 4)
_SO_TIMESTAMP = getattr(socket, "SO_TIMESTAMP", 29)
_SO_RXQ_OVFL = getattr(socket, "SO_RXQ_OVFL", 40)
_CAN_ERR_MASK = 0x1FFFFFFF

_DEFAULT_START_UTC = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


class FakeClock:
    """Test time: a monotonic clock and a wall clock that the test moves.

    ``advance(s)`` moves both clocks forward by ``s`` seconds (time passing).
    ``jump(s)`` moves only the wall clock, forward or back (a clock step), so
    timers on the monotonic clock are not affected (X27).
    """

    def __init__(self, start_utc: Optional[datetime] = None, start_mono: float = 1000.0) -> None:
        start = _DEFAULT_START_UTC if start_utc is None else start_utc
        if start.tzinfo is None:
            raise ValueError("start_utc must be timezone-aware (UTC)")
        self._mono = float(start_mono)
        self._wall = start.astimezone(timezone.utc)
        self._jumps: list[tuple[float, float]] = []  # (at_mono, s), from a fault plan

    def mono(self) -> float:
        return self._mono

    def wall(self) -> datetime:
        return self._wall

    def advance(self, s: float) -> None:
        if s < 0:
            raise ValueError("monotonic time never goes back; use jump() for a wall-clock step")
        target = self._mono + s
        # Apply scheduled jumps in order, at the moment monotonic time reaches them.
        while self._jumps and self._jumps[0][0] <= target:
            at, jump_s = self._jumps.pop(0)
            self._move(at - self._mono)
            self._wall += timedelta(seconds=jump_s)
        self._move(target - self._mono)

    def jump(self, s: float) -> None:
        self._wall += timedelta(seconds=s)

    def _move(self, s: float) -> None:
        if s > 0:
            self._mono += s
            self._wall += timedelta(seconds=s)

    def _schedule_jump(self, at_mono: float, s: float) -> None:
        if at_mono <= self._mono:
            self.jump(s)
            return
        self._jumps.append((at_mono, s))
        self._jumps.sort(key=lambda j: j[0])


class _HostClock:
    """The host's clocks, when no FakeClock is given."""

    def mono(self) -> float:
        return time.monotonic()

    def wall(self) -> datetime:
        return datetime.now(timezone.utc)


class _Window:
    def __init__(
        self, kind: str, start: float, end: float, ops: tuple[str, ...] = (), delay_s: float = 0.0
    ) -> None:
        self.kind = kind
        self.start = start
        self.end = end
        self.ops = ops
        self.delay_s = delay_s

    def active(self, mono: float) -> bool:
        return self.start <= mono < self.end


class DesktopPlatform:
    """The desktop (``vcan0``) implementation of ``Platform``."""

    def __init__(
        self,
        fault_plan: Sequence[FaultSpec] = (),
        clock: Optional[FakeClock] = None,
        *,
        interface: str = "vcan0",
        bitrate: int = 250000,
        root: Optional[Path] = None,
    ) -> None:
        self._clock: Any = _HostClock() if clock is None else clock
        self._fake = clock
        self._interface = interface
        self._bitrate = bitrate
        self._windows: list[_Window] = []
        self._load_plan(fault_plan)

        base = Path(tempfile.mkdtemp(prefix="j1939logger-")) if root is None else Path(root)
        self._paths = Paths(card=base / "card", flash=base / "flash", keys=base / "keys")
        for p in (self._paths.card, self._paths.flash, self._paths.keys):
            p.mkdir(parents=True, exist_ok=True)

        self._wake_mono = self._clock.mono()
        self._ready_mono: Optional[float] = None
        self.lights: list[str] = []  # every pattern set, in order (for tests)
        self.watchdog_kicks = 0  # number of kicks (for tests)
        self.listen_only: Optional[bool] = None  # mode of the last open_can() (for tests)

    # -- fault plan -------------------------------------------------------

    def _load_plan(self, plan: Sequence[FaultSpec]) -> None:
        for entry in plan:
            if len(entry) != 3:
                raise ValueError(f"fault plan entry must be (at_mono, kind, args): {entry!r}")
            at_mono, kind, args = entry
            if kind not in FAULT_KINDS:
                raise ValueError(f"unknown fault kind {kind!r}; kinds come from docs/errors.md")
            if kind not in DELIVERED_FAULT_KINDS:
                raise NotImplementedError(
                    f"fault kind {kind!r} is not injected by the platform fault plan "
                    "(docs/design-changes.md, DC-5)"
                )
            opts = dict(args or {})
            at = float(at_mono)
            if kind == "clock_jump":
                if self._fake is None:
                    raise ValueError("clock_jump needs a FakeClock")
                if "s" not in opts:
                    raise ValueError("clock_jump needs args {'s': seconds}")
                self._fake._schedule_jump(at, float(opts["s"]))
                continue
            for_s = opts.get("for_s")
            end = float("inf") if for_s is None else at + float(for_s)
            ops: tuple[str, ...] = ()
            delay_s = 0.0
            if kind in OPS_BY_KIND:
                ops = tuple(opts.get("ops", OPS_BY_KIND[kind]))
                if not ops or not set(ops) <= set(OPS_BY_KIND[kind]):
                    raise ValueError(f"{kind} applies to {OPS_BY_KIND[kind]}: {ops!r}")
                if kind == "slow_sync":
                    if "s" not in opts:
                        raise ValueError("slow_sync needs args {'s': seconds}")
                    delay_s = float(opts["s"])
            self._windows.append(_Window(kind, at, end, ops, delay_s))

    def _active(self, kind: str) -> bool:
        mono = self._clock.mono()
        return any(w.kind == kind and w.active(mono) for w in self._windows)

    # -- Platform ---------------------------------------------------------

    def open_can(self, listen_only: bool) -> socket.socket:
        if self._active("can_missing"):
            raise PlatformError("can_missing", "fault plan")
        if not hasattr(socket, "AF_CAN"):
            raise PlatformError("can_missing", "AF_CAN is not available on this system")
        try:
            sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        except OSError as exc:
            raise PlatformError("can_missing", str(exc)) from exc
        try:
            sock.setsockopt(socket.SOL_SOCKET, _SO_TIMESTAMP, 1)
            sock.setsockopt(socket.SOL_SOCKET, _SO_RXQ_OVFL, 1)
            sock.setsockopt(_SOL_CAN_RAW, _CAN_RAW_ERR_FILTER, _CAN_ERR_MASK)
            sock.setsockopt(_SOL_CAN_RAW, _CAN_RAW_RECV_OWN_MSGS, 1)
            sock.bind((self._interface,))
        except OSError as exc:
            sock.close()
            raise PlatformError("can_missing", f"{self._interface}: {exc}") from exc
        # vcan has no controller mode: listen-only is recorded, not applied.
        self.listen_only = listen_only
        return sock

    def bitrate_check(self) -> Optional[int]:
        if self._active("no_bitrate"):
            return None
        return self._bitrate

    def set_light(self, pattern: str) -> None:
        if pattern not in LIGHT_PATTERNS:
            raise ValueError(f"light pattern must be one of {LIGHT_PATTERNS}: {pattern!r}")
        self.lights.append(pattern)

    def now(self) -> ClockReading:
        mono = self._clock.mono()
        if self.rtc_ok():
            return ClockReading(wall_utc=self._clock.wall(), mono=mono, source="rtc", valid=True)
        return ClockReading(wall_utc=None, mono=mono, source="elapsed", valid=False)

    def rtc_ok(self) -> bool:
        return not self._active("rtc_invalid")

    def on_wake(self) -> tuple[float, float]:
        if self._ready_mono is None:
            self._ready_mono = self._clock.mono()
        return (self._wake_mono, self._ready_mono)

    def watchdog_kick(self) -> None:
        self.watchdog_kicks += 1

    def paths(self) -> Paths:
        return self._paths

    def fault(self, op: str) -> None:
        if op not in FAULT_OPS:
            raise ValueError(f"operation must be one of {FAULT_OPS}: {op!r}")
        mono = self._clock.mono()
        for w in self._windows:
            if op in w.ops and w.active(mono):
                if w.kind == "slow_sync":
                    self._delay(w.delay_s)
                    return
                raise PlatformError(w.kind, f"fault plan, {op}")

    def _delay(self, s: float) -> None:
        if self._fake is not None:
            self._fake.advance(s)
        else:
            time.sleep(s)
