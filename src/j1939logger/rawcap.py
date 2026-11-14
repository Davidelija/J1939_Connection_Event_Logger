"""rawcap: raw candump windows around events (docs/modules.md section 4, v1, frozen for step 6).

Layer 1. Built to DC-20 (LOG-10).

* ``start(conn, ts_mono, before)`` opens a capture for a ``connection_start``
  or ``control_flag`` at ``ts_mono``, with ``before``: the ring's frames from
  ``logging.raw_before_s`` before it (``capture.window``, passed by ``session``).
  It returns the name for the record's ``raw_capture`` field,
  ``raw/s<session 6 digits>_c<conn>_e<n>.log`` (``n`` counts that connection's
  captures), or None when no capture starts: ``limits.raw_mb_per_session``
  is used up, or ``stop()`` was called because only the reserve is left
  (LOG-22).
* ``feed(frames)`` adds later frames to every open capture until
  ``logging.raw_after_s`` after its event; ``poll(now_mono)`` writes each
  capture whose window has closed; ``close()`` writes the rest with what they
  have (session end).
* Files are candump log format: ``(seconds.micros) can0 ID#DATA``, IDs as 8
  hex digits for 29-bit and 3 for 11-bit, ``R`` for remote frames and the
  CAN error flag (0x20000000) on error frames.
* ``platform.fault("card_write")`` is called before each write (DC-5); a
  write error is a high ``fault`` record from ``take_faults()``, never an
  exception (LOG-22).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from j1939logger.platform.interface import Platform
from j1939logger.types import Frame, PlatformError, Record

__all__ = ["RawCap", "candump_line"]

CAN_ERR_FLAG = 0x20000000
INTERFACE = "can0"


def candump_line(f: Frame) -> str:
    """One frame in candump log format, as ``candump -l`` writes it."""
    cid = f.can_id | (CAN_ERR_FLAG if f.error else 0)
    ident = f"{cid:08X}" if (f.extended or f.error) else f"{cid:03X}"
    data = "R" if f.remote else f.data.hex().upper()
    return f"({f.ts_kernel:.6f}) {INTERFACE} {ident}#{data}\n"


@dataclass
class _Open:
    name: str
    end_mono: float
    frames: list[Frame] = field(default_factory=list)
    last_mono: float = float("-inf")


class RawCap:
    def __init__(self, platform: Platform, settings: Mapping[str, Any], session: int) -> None:
        self._platform = platform
        self._before_s = float(settings["logging.raw_before_s"])
        self._after_s = float(settings["logging.raw_after_s"])
        self._budget = float(settings["limits.raw_mb_per_session"]) * 1024 * 1024
        self._session = session
        self._dir = platform.paths().card / "raw"
        self._open: list[_Open] = []
        self._count: dict[int, int] = {}
        self._faults: list[Record] = []
        self.bytes_written = 0
        self.stopped: Optional[str] = None  # why no new capture starts, if so
        self.written: list[str] = []

    @property
    def before_s(self) -> float:
        return self._before_s

    def stop(self, reason: str) -> None:
        """No new capture starts for the rest of the session (LOG-22: only the reserve left)."""
        self.stopped = reason

    def start(self, conn: int, ts_mono: float, before: Iterable[Frame]) -> Optional[str]:
        """Open a capture for an event at ``ts_mono``; the name for ``raw_capture``, or None."""
        if self.stopped is not None or self.bytes_written >= self._budget:
            return None
        n = self._count.get(conn, 0) + 1
        self._count[conn] = n
        name = f"raw/s{self._session:06d}_c{conn}_e{n}.log"
        cap = _Open(name, ts_mono + self._after_s)
        lo = ts_mono - self._before_s
        for f in before:
            if lo <= f.ts_mono <= cap.end_mono:
                cap.frames.append(f)
                cap.last_mono = max(cap.last_mono, f.ts_mono)
        self._open.append(cap)
        return name

    def feed(self, frames: Iterable[Frame]) -> None:
        """Later frames, for every capture whose window is still open."""
        if not self._open:
            return
        for f in frames:
            for cap in self._open:
                if cap.last_mono < f.ts_mono <= cap.end_mono:
                    cap.frames.append(f)
                    cap.last_mono = f.ts_mono

    def poll(self, now_mono: float) -> list[str]:
        """Write the captures whose window has closed; returns their names."""
        done = [c for c in self._open if now_mono > c.end_mono]
        self._open = [c for c in self._open if now_mono <= c.end_mono]
        return [c.name for c in done if self._write(c)]

    def close(self) -> list[str]:
        """Write every open capture with what it has (session end)."""
        done, self._open = self._open, []
        return [c.name for c in done if self._write(c)]

    @property
    def open_captures(self) -> int:
        return len(self._open)

    def take_faults(self) -> list[Record]:
        out, self._faults = self._faults, []
        return out

    def _write(self, cap: _Open) -> bool:
        text = "".join(candump_line(f) for f in cap.frames).encode("ascii")
        path: Path = self._platform.paths().card / cap.name
        try:
            self._platform.fault("card_write")
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(text)
        except (OSError, PlatformError) as exc:
            kind = exc.kind if isinstance(exc, PlatformError) else type(exc).__name__
            self._faults.append(
                Record(
                    "fault",
                    "high",
                    None,
                    None,
                    {
                        "cause": f"storage error ({kind}) writing {cap.name}",
                        "logger_action": "raw capture lost; event records continue",
                    },
                )
            )
            return False
        self.bytes_written += len(text)
        self.written.append(cap.name)
        return True
