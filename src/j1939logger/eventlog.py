"""eventlog: append records to the session file and keep the hash chain.

docs/modules.md section 4, contract v1. Layer 1; the only writer of session
files (CLAUDE.md rule 15). Frozen for steps 1 and 2:
appending a ``Record``, the hash rule, one ``write()`` per record to an
``O_APPEND`` file, ``sync_now()`` and the last hash (step 1); the periodic sync
thread (``logging.sync_interval_s``, LOG-3), parts (``roll_over()``, record
numbers continue across parts, DC-11), records without a valid time
(``elapsed_s``, DC-10) and ``scan_tail()``, which rebuilds the last hash from
the last complete line of a session file after a crash (step 2).

Each line is one record as compact JSON, keys in this order: ``rec``,
``type``, ``sev``, ``utc``, ``written``, ``veh_time``, ``conn`` (when set),
the type-specific fields, ``clock_valid``, ``clock_source``, ``prev``,
``hash`` (docs/log-format.md and the session 142 example). While the clock
source is ``elapsed`` there is no UTC: ``utc`` and ``written`` are null and
``elapsed_s`` (seconds since wake when written) follows ``veh_time`` (DC-10). ``hash`` is the
SHA-256, as 64 lowercase hex characters, of the UTF-8 bytes of ``prev``
followed by the record without ``hash``, serialized the same way.

Storage errors never crash the logger: the record is not written, the chain
is left as it was, and a ``fault`` record (LOG-22) waits in ``take_faults()``.
A repeated storage error is reported once, with a count (CLAUDE.md rule 14): an
outage has one ``fault`` record. It is handed out again until it is written, and
records lost meanwhile are only counted; when it is written, its
``logger_action`` gives the count.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.clock import Clock
from j1939logger.platform.interface import Platform
from j1939logger.types import PlatformError, Record

__all__ = [
    "EventLog",
    "Tail",
    "ZERO_HASH",
    "record_hash",
    "format_utc",
    "format_veh_time",
    "scan_tail",
]

ZERO_HASH = "0" * 64


# logger_action for an outage that began with a sync failure and lost no record (QC-4 E2)
SYNC_FAILED = "sync failed; records since the last sync may not be on the card"


def format_utc(t: Optional[datetime]) -> Optional[str]:
    """ISO 8601 UTC with milliseconds, for example 2026-11-06T14:02:11.402Z."""
    if t is None:
        return None
    t = t.astimezone(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def format_veh_time(t: Optional[datetime]) -> Optional[str]:
    """Vehicle time in whole seconds, for example 2026-11-06T14:02:12Z."""
    if t is None:
        return None
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def record_hash(prev: str, body: dict[str, Any]) -> str:
    """SHA-256 of ``prev`` followed by the record without its hash (log-format)."""
    return hashlib.sha256((prev + _dumps(body)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Tail:
    """The end of a session file, read after a restart (LOG-5, LOG-12)."""

    last_hash: Optional[str]  # hash of the last complete record, None if there is none
    last_type: Optional[str]  # its record type
    last_rec: int  # its record number (0 if none)
    bytes_cut_off: int  # length of an incomplete last line (power loss); never rewritten


def scan_tail(path: Path) -> Tail:
    """Read the last complete record of a session file; an incomplete last line is reported."""
    data = Path(path).read_bytes()
    cut = 0
    if data and not data.endswith(b"\n"):
        end = data.rfind(b"\n")
        cut = len(data) - (end + 1)
        data = data[: end + 1]
    for line in reversed(data.splitlines()):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # a damaged line: the verifier reports it; keep looking back
        if isinstance(rec, dict) and isinstance(rec.get("hash"), str):
            return Tail(rec["hash"], rec.get("type"), int(rec.get("rec", 0)), cut)
    return Tail(None, None, 0, cut)


class EventLog:
    """Appends records to a session file (and its parts)."""

    def __init__(
        self,
        platform: Platform,
        clock: Clock,
        path: Path,
        session: int,
        prev: str,
        first_rec: int = 1,
    ) -> None:
        if len(prev) != 64:
            raise ValueError("prev must be 64 lowercase hex characters")
        self._platform = platform
        self._clock = clock
        self._path = Path(path)
        self._session = session
        self._prev = prev
        self._rec = first_rec
        self._fd: Optional[int] = None
        self._faults: list[Record] = []
        self._outage: Optional[Record] = None  # the outage's one fault record (rule 14)
        self._outage_lost = 0  # records not written since the outage began
        self._lock = threading.Lock()
        self._sync_stop = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None

    @property
    def last_hash(self) -> str:
        return self._prev

    @property
    def path(self) -> Path:
        return self._path

    @property
    def next_rec(self) -> int:
        return self._rec

    def roll_over(self, new_path: Path) -> None:
        """Continue the session in a new part file; record numbers and the chain continue."""
        with self._lock:
            self._close_fd()
            self._path = Path(new_path)

    def start_sync(self, interval_s: float) -> None:
        """Sync every ``logging.sync_interval_s`` on a thread of its own (LOG-3)."""
        if self._sync_thread is not None:
            return
        self._sync_stop.clear()

        def run() -> None:
            while not self._sync_stop.wait(interval_s):
                self.sync_now()

        self._sync_thread = threading.Thread(target=run, name="eventlog-sync", daemon=True)
        self._sync_thread.start()

    def stop_sync(self) -> None:
        self._sync_stop.set()
        if self._sync_thread is not None:
            self._sync_thread.join(timeout=2.0)
            self._sync_thread = None

    def _open(self) -> int:
        if self._fd is None:
            self._platform.fault("card_write")
            self._fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        return self._fd

    def append(self, record: Record) -> Optional[str]:
        """Write one record; returns its event ID, or None if storage failed."""
        with self._lock:
            return self._append(record)

    def _append(self, record: Record) -> Optional[str]:
        if record is self._outage:
            record.fields["logger_action"] = self._outage_action()
        reading = self._clock.now()
        rec = self._rec
        body: dict[str, Any] = {
            "rec": rec,
            "type": record.type,
            "sev": record.sev,
            "utc": format_utc(record.utc) if reading.wall_utc is not None else None,
            "written": format_utc(reading.wall_utc),
            "veh_time": format_veh_time(record.veh_time),
        }
        if reading.wall_utc is None:
            body["elapsed_s"] = self._clock.elapsed_s(reading.mono)  # DC-10
        if record.conn is not None:
            body["conn"] = record.conn
        for key, value in record.fields.items():
            if key in body or key in ("clock_valid", "clock_source", "prev", "hash"):
                raise ValueError(f"field {key!r} is set by eventlog")
            body[key] = value
        body["clock_valid"] = reading.valid
        body["clock_source"] = reading.source
        body["prev"] = self._prev
        digest = record_hash(self._prev, body)
        body["hash"] = digest
        line = (_dumps(body) + "\n").encode("utf-8")
        try:
            fd = self._open()
            self._platform.fault("card_write")
            written = os.write(fd, line)  # one write() per record (LOG-3)
            if written != len(line):
                raise OSError(f"short write: {written} of {len(line)} bytes")
        except (PlatformError, OSError) as exc:
            self._storage_fault(exc, record)
            return None
        self._prev = digest
        self._rec = rec + 1
        record.event_id = f"{self._session}-{rec}"
        if record is self._outage:
            self._outage, self._outage_lost = None, 0  # the outage is reported: it is over
        return record.event_id

    def sync_now(self) -> bool:
        """fsync the session file (connection_start is synced at once, DET-16)."""
        with self._lock:
            if self._fd is None:
                return True
            try:
                self._platform.fault("card_sync")
                os.fsync(self._fd)
            except (PlatformError, OSError) as exc:
                self._storage_fault(exc)
                return False
            return True

    def close(self) -> None:
        self.stop_sync()
        with self._lock:
            self._close_fd()

    def _close_fd(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def take_faults(self) -> list[Record]:
        """Storage-error fault records waiting to be logged or shown (LOG-22).

        Takes the lock: the sync thread adds faults too (QC-4 E1).
        """
        with self._lock:
            out, self._faults = self._faults, []
        return out

    def _outage_action(self) -> str:
        """``logger_action`` for the outage's fault record, from what was lost (rule 14)."""
        if self._outage_lost == 0:
            return SYNC_FAILED  # the outage began with a sync failure; no record lost (E2)
        if self._outage_lost == 1:
            return "record not written"
        return f"{self._outage_lost} records not written; recording continues"

    def _storage_fault(self, exc: BaseException, record: Optional[Record] = None) -> None:
        kind = exc.kind if isinstance(exc, PlatformError) else type(exc).__name__
        if self._fd is not None and isinstance(exc, PlatformError) and exc.kind == "card_removed":
            self._close_fd()  # reopened on the next write, after reinsertion
        if self._outage is not None:  # the same outage: not reported again (rule 14)
            if record is self._outage:
                if not any(f is record for f in self._faults):
                    self._faults.append(record)  # handed out again until it is written
            elif record is not None:
                self._outage_lost += 1
            return
        self._outage = Record(
            type="fault",
            sev="high",
            utc=self._clock.to_utc(self._clock.mono()),
            veh_time=None,
            fields={"cause": f"storage error ({kind})", "logger_action": ""},
        )
        self._outage_lost = 1 if record is not None else 0
        self._outage.fields["logger_action"] = self._outage_action()
        self._faults.append(self._outage)
