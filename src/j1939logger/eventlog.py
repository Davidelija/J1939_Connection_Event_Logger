"""eventlog: append records to the session file and keep the hash chain.

docs/modules.md section 4, contract v1. Layer 1; the only writer of session
files (CLAUDE.md rule 15). This is the part frozen for step 1 (append only,
DC-8): appending a ``Record``, the hash rule, one ``write()`` per record to an
``O_APPEND`` file, ``sync_now()`` and the last hash. Session parts, roll-over,
the sync thread and rebuilding the last hash after a crash come in step 2.

Each line is one record as compact JSON, keys in this order: ``rec``,
``type``, ``sev``, ``utc``, ``written``, ``veh_time``, ``conn`` (when set),
the type-specific fields, ``clock_valid``, ``clock_source``, ``prev``,
``hash`` (docs/log-format.md and the session 142 example). ``hash`` is the
SHA-256, as 64 lowercase hex characters, of the UTF-8 bytes of ``prev``
followed by the record without ``hash``, serialized the same way.

Storage errors never crash the logger: the record is not written, the chain
is left as it was, and a ``fault`` record (LOG-22) waits in ``take_faults()``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.clock import Clock
from j1939logger.platform.interface import Platform
from j1939logger.types import PlatformError, Record

__all__ = ["EventLog", "ZERO_HASH", "record_hash", "format_utc", "format_veh_time"]

ZERO_HASH = "0" * 64


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


class EventLog:
    """Appends records to one session file."""

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

    @property
    def last_hash(self) -> str:
        return self._prev

    @property
    def path(self) -> Path:
        return self._path

    def _open(self) -> int:
        if self._fd is None:
            self._platform.fault("card_write")
            self._fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        return self._fd

    def append(self, record: Record) -> Optional[str]:
        """Write one record; returns its event ID, or None if storage failed."""
        reading = self._clock.now()
        rec = self._rec
        body: dict[str, Any] = {
            "rec": rec,
            "type": record.type,
            "sev": record.sev,
            "utc": format_utc(record.utc),
            "written": format_utc(reading.wall_utc),
            "veh_time": format_veh_time(record.veh_time),
        }
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
            self._storage_fault(exc)
            return None
        self._prev = digest
        self._rec = rec + 1
        record.event_id = f"{self._session}-{rec}"
        return record.event_id

    def sync_now(self) -> bool:
        """fsync the session file (connection_start is synced at once, DET-16)."""
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
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def take_faults(self) -> list[Record]:
        """Storage-error fault records waiting to be logged or shown (LOG-22)."""
        out, self._faults = self._faults, []
        return out

    def _storage_fault(self, exc: BaseException) -> None:
        kind = exc.kind if isinstance(exc, PlatformError) else type(exc).__name__
        if self._fd is not None and isinstance(exc, PlatformError) and exc.kind == "card_removed":
            self.close()  # reopened on the next write, after reinsertion
        self._faults.append(
            Record(
                type="fault",
                sev="high",
                utc=self._clock.to_utc(self._clock.mono()),
                veh_time=None,
                fields={"cause": f"storage error ({kind})", "logger_action": "record not written"},
            )
        )
