"""detect: when a device connects (step 1 minimal form, DC-9).

Layer 3: no I/O; time only through ``clock``. The full contract (moves,
conflicts, never-claiming devices, sweeps, 60 s silence end) is built in
step 4; classification moves to ``identify`` in step 5.

Step 1 behaviour:

* An address claim (PGN 60928) from a NAME that is not in the inventory opens
  a connection keyed by NAME (DET-1, DET-15) and returns a ``connection_start``
  record. Classification by wake timing (DET-13): a first claim within
  ``classify.wake_window_s`` of the session's first frame is "vehicle ECU not
  in baseline", a later one "external device (unrecognized)"; both high,
  capped at notice when the session is untrained (no inventory, TRN-9).
* An approved external device in the inventory gets an info
  ``connection_start`` in the short form: NAME and entry ID (DET-17).
* Baseline ECUs get no record. The logger's own frames are ignored (NP-15).
* A NAME already connected this session does not start a second connection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from j1939logger.clock import Clock
from j1939logger.decode import PGN_ADDRESS_CLAIM, decode_name
from j1939logger.types import Connection, J1939Msg, Record

__all__ = ["Detect", "InventoryEntry"]

APPROVED = "external device (approved)"
NOT_IN_BASELINE = "vehicle ECU not in baseline"
UNRECOGNIZED = "external device (unrecognized)"


class InventoryEntry:
    """What step 1 needs from an inventory entry (until the inventory module, step 6)."""

    def __init__(self, entry: str, category: str) -> None:
        self.entry = entry
        self.category = category


def _minutes_or_seconds(s: float) -> str:
    if s >= 60:
        return f"{s / 60:.0f} min"
    return f"{s:.1f} s"


class Detect:
    def __init__(
        self,
        clock: Clock,
        inventory: Optional[Mapping[int, InventoryEntry]],
        wake_window_s: float,
    ) -> None:
        self._clock = clock
        self._inventory = inventory
        self._untrained = inventory is None
        self._wake_window_s = wake_window_s
        self._first_mono: Optional[float] = None
        self._open: dict[tuple[str, int], Connection] = {}
        self._next_conn = 1

    @property
    def connections(self) -> list[Connection]:
        return list(self._open.values())

    def on_message(self, msg: J1939Msg) -> list[Record]:
        if msg.own:
            return []
        if self._first_mono is None:
            self._first_mono = msg.ts_mono
        if msg.pgn != PGN_ADDRESS_CLAIM or len(msg.data) != 8:
            return []
        value = int.from_bytes(msg.data, "little")
        key = ("name", value)
        conn = self._open.get(key)
        if conn is not None:
            conn.last_mono = msg.ts_mono
            conn.sa = msg.sa
            return []
        known = self._inventory.get(value) if self._inventory is not None else None
        if known is not None and known.category != APPROVED:
            return []  # baseline vehicle ECU: no connection record (LOG-7)
        return [self._start(msg, value, known)]

    def _start(self, msg: J1939Msg, value: int, known: Optional[InventoryEntry]) -> Record:
        name = decode_name(value)
        since = msg.ts_mono - (self._first_mono if self._first_mono is not None else msg.ts_mono)
        at_start = since <= self._wake_window_s
        trigger = "address claim at session start" if at_start else "new address claim"
        if known is not None:
            category, sev = APPROVED, "info"
            fields: dict[str, object] = {
                "sa": msg.sa,
                "name": f"0x{value:016X}",
                "trigger": trigger,
                "in_inventory": True,
                "entry": known.entry,
                "category": category,
                "classification_rule": "in inventory",
            }
        else:
            category = NOT_IN_BASELINE if at_start else UNRECOGNIZED
            sev = "notice" if self._untrained else "high"
            fields = {
                "sa": msg.sa,
                "name": f"0x{value:016X}",
                "name_fields": {
                    "aac": name.aac,
                    "industry_group": name.industry_group,
                    "vehicle_system": name.vehicle_system,
                    "function": name.function,
                    "function_instance": name.function_instance,
                    "ecu_instance": name.ecu_instance,
                    "mfr_code": name.mfr_code,
                    "identity": f"0x{name.identity:X}",
                },
                "trigger": trigger,
                "in_inventory": False,
                "category": category,
                "classification_rule": "wake timing",
                "classification_detail": (
                    f"first claim {_minutes_or_seconds(since)} after the session's first frame"
                ),
            }
        conn = Connection(
            conn=self._next_conn,
            key=("name", value),
            sa=msg.sa,
            name=name,
            start_mono=msg.ts_mono,
            last_mono=msg.ts_mono,
            category=category,
        )
        self._open[("name", value)] = conn
        self._next_conn += 1
        return Record(
            type="connection_start",
            sev=sev,
            utc=self._clock.to_utc(msg.ts_mono),
            veh_time=None,
            fields=fields,
            conn=conn.conn,
        )
