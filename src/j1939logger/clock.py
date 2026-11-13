"""clock: the one source of time and its validity (docs/modules.md section 4, contract v2).

Layer 1. Reads time only from the platform (CLAUDE.md rule 14) and never sets
the system clock (LOG-16).

* ``now()``: wall time and its source. ``rtc`` when the platform's real-time
  clock is valid; otherwise ``vehicle`` once a vehicle Time/Date reply has set
  an offset; otherwise ``elapsed`` with no wall time. ``valid`` is whether the
  real-time clock is valid (log-format ``clock_valid``).
* ``to_utc(ts_mono)``: the only way any module turns a frame or event time
  into a record's ``utc``. None while the source is ``elapsed``.
* ``veh_time(ts_mono)``: vehicle time for an event from the Time/Date
  offset, whole seconds; None before the first reply (v2, DC-10).
* ``elapsed_s(ts_mono)``: seconds since wake, to the millisecond; records
  carry it while the source is ``elapsed`` (DC-10).
* ``on_time_date(msg)``: a vehicle Time/Date (PGN 65254) message. The first
  one yields a ``time_sync`` record; a reply more than ``clock.max_skew_min``
  from a valid real-time clock yields a notice ``fault`` and the real-time
  clock is kept.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from j1939logger.platform.interface import Platform
from j1939logger.types import ClockReading, J1939Msg, Record

__all__ = ["Clock", "parse_time_date", "PGN_TIME_DATE"]

PGN_TIME_DATE = 65254


def parse_time_date(data: bytes) -> Optional[datetime]:
    """Vehicle Time/Date (PGN 65254, SPNs 959 to 964) as UTC, or None if not available.

    Seconds are 0.25 s per bit (the fraction is dropped, log-format ``veh_time``),
    days 0.25 per bit, years offset 1985. Local offsets (SPNs 1601, 1602) are not
    applied: the fields are UTC.
    """
    if len(data) < 6:
        return None
    sec_raw, minute, hour, month, day_raw, year_raw = data[:6]
    if sec_raw > 239 or minute > 59 or hour > 23 or not 1 <= month <= 12:
        return None
    if day_raw > 250 or year_raw > 250:
        return None
    day = (day_raw + 3) // 4  # 0.25 days/bit; 1..4 is day 1
    try:
        return datetime(
            1985 + year_raw, month, day, hour, minute, sec_raw // 4, tzinfo=timezone.utc
        )
    except ValueError:
        return None


class Clock:
    """Time for the logger: real-time clock, vehicle offset, or time since wake."""

    def __init__(
        self, platform: Platform, max_skew_min: float, wake_mono: Optional[float] = None
    ) -> None:
        """``wake_mono`` is the monotonic time of wake; it defaults to now."""
        self._platform = platform
        self._wake_mono = platform.now().mono if wake_mono is None else wake_mono
        self._max_skew_s = max_skew_min * 60.0
        self._vehicle_offset: Optional[float] = None  # vehicle UTC seconds minus mono
        self._synced = False

    # -- reading ------------------------------------------------------------

    def now(self) -> ClockReading:
        r = self._platform.now()
        if r.valid and r.wall_utc is not None:
            return r
        if self._vehicle_offset is not None:
            wall = _epoch(r.mono + self._vehicle_offset)
            return ClockReading(wall_utc=wall, mono=r.mono, source="vehicle", valid=False)
        return ClockReading(wall_utc=None, mono=r.mono, source="elapsed", valid=False)

    def mono(self) -> float:
        return self._platform.now().mono

    def to_utc(self, ts_mono: float) -> Optional[datetime]:
        r = self.now()
        if r.wall_utc is None:
            return None
        return r.wall_utc - timedelta(seconds=r.mono - ts_mono)

    def veh_time(self, ts_mono: float) -> Optional[datetime]:
        """Vehicle time for an event, whole seconds; None before the first Time/Date reply."""
        if self._vehicle_offset is None:
            return None
        return _epoch(ts_mono + self._vehicle_offset).replace(microsecond=0)

    def elapsed_s(self, ts_mono: float) -> float:
        """Seconds since wake, to the millisecond (records without a valid time, DC-10)."""
        return round(ts_mono - self._wake_mono, 3)

    # -- vehicle time ---------------------------------------------------------

    def on_time_date(self, msg: J1939Msg) -> list[Record]:
        """Handle a Time/Date message; returns ``time_sync`` or ``fault`` records."""
        if msg.pgn != PGN_TIME_DATE or msg.own:
            return []
        vehicle = parse_time_date(msg.data)
        if vehicle is None:
            return []
        records: list[Record] = []
        rtc = self._platform.now()
        vehicle_s = vehicle.timestamp()
        if rtc.valid and rtc.wall_utc is not None:
            logger_s = (rtc.wall_utc - timedelta(seconds=rtc.mono - msg.ts_mono)).timestamp()
        else:
            logger_s = None
        if self._vehicle_offset is None:
            self._vehicle_offset = vehicle_s - msg.ts_mono
        utc = self.to_utc(msg.ts_mono)
        if not self._synced:
            self._synced = True
            offset = None if logger_s is None else round(vehicle_s - logger_s, 3)
            records.append(
                Record(
                    type="time_sync",
                    sev="info",
                    utc=utc,
                    veh_time=vehicle,
                    fields={"source_sa": msg.sa, "offset_s": offset},
                )
            )
        if logger_s is not None and abs(vehicle_s - logger_s) > self._max_skew_s:
            records.append(
                Record(
                    type="fault",
                    sev="notice",
                    utc=utc,
                    veh_time=vehicle,
                    fields={
                        "cause": "vehicle time and real-time clock differ by more than "
                        f"{self._max_skew_s / 60:g} minutes",
                        "logger_action": "kept the real-time clock",
                    },
                )
            )
        return records


def _epoch(s: float) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=s)
