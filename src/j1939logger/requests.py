"""requests: the logger's scheduled and identity requests (docs/modules.md section 4, v1).

Layer 3, frozen for step 3: no I/O; time only through ``clock``. It produces
``TxRequest``s (Request, PGN 59904, for a PGN in ``requests.allow_list``) for
``session`` to pass to ``transmit``, and tells ``transmit`` when a destination
is free again (``release``, DC-12).

* Session start (NP-11, NP-12): a global Request for Address Claim (the
  sweep), then Time/Date (65254) and VIN (65260) to ``requests.vin_sa``.
* Sweeps every ``requests.sweep_interval_min`` (NP-11). Claims heard within
  ``requests.timeout_s`` of a sweep are its answer; a ``sweep`` record is
  written for the first sweep of the session and for any sweep that finds a
  change (LOG-9). The first completed sweep sets ``first_sweep_done``
  (DET-2's first-sweep wait).
* Identity (NP-13): Component ID (65259), Software ID (65242) and ECU ID
  (64965) from each source address not held by a known NAME (``identify()``);
  a known NAME at a new address is not asked.
* Timeouts (NP-14): each request waits ``requests.timeout_s`` for a reply or
  NACK and is retried ``requests.retries`` times; the outcome (reply, NACK, no
  reply) is recorded as a ``RequestOutcome``. A request that failed is not
  repeated in the session.
* One request per destination at a time is kept here as well as in
  ``transmit``; the timer starts when the request is handed to ``transmit``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from j1939logger.clock import Clock
from j1939logger.types import J1939Msg, Record, TxRequest

__all__ = [
    "Requests",
    "RequestOutcome",
    "PGN_TIME_DATE",
    "PGN_VIN",
    "PGN_COMPONENT_ID",
    "PGN_SOFTWARE_ID",
    "PGN_ECU_ID",
]

PGN_REQUEST = 59904
PGN_ACK = 59392
PGN_CLAIM = 60928
PGN_TIME_DATE = 65254
PGN_VIN = 65260
PGN_COMPONENT_ID = 65259
PGN_SOFTWARE_ID = 65242
PGN_ECU_ID = 64965
IDENTITY = (PGN_COMPONENT_ID, PGN_SOFTWARE_ID, PGN_ECU_ID)
GLOBAL = 255
NAMES = {
    PGN_COMPONENT_ID: "Component ID",
    PGN_SOFTWARE_ID: "Software ID",
    PGN_ECU_ID: "ECU ID",
    PGN_VIN: "VIN",
    PGN_TIME_DATE: "Time/Date",
}


@dataclass(frozen=True)
class RequestOutcome:
    """The result of one request, for ``identify`` (and the VIN check)."""

    conn: Optional[int]
    pgn: int
    da: int
    outcome: str  # "reply" | "NACK" | "no reply" (requirements enum)
    value: Optional[bytes]
    attempts: int
    sent_mono: float


@dataclass
class _Pending:
    pgn: int
    da: int
    conn: Optional[int]
    attempt: int = 0
    sent_mono: float = 0.0
    first_sent_mono: float = 0.0


class Requests:
    def __init__(
        self,
        clock: Clock,
        settings: Mapping[str, Any],
        known_names: Iterable[int],
        logger_name: int,
        release: Callable[[int], None],
    ) -> None:
        self._clock = clock
        self._allow = frozenset(settings["requests.allow_list"])
        self._vin_sa = int(settings["requests.vin_sa"])
        self._timeout = float(settings["requests.timeout_s"])
        self._retries = int(settings["requests.retries"])
        self._interval = float(settings["requests.sweep_interval_min"]) * 60.0
        self._known = frozenset(known_names)
        self._logger_name = logger_name
        self._release = release
        self._queue: dict[int, deque[_Pending]] = {}
        self._active: dict[int, _Pending] = {}
        self._failed: set[tuple[int, int]] = set()  # (pgn, da) not repeated this session
        self._asked: set[tuple[int, int]] = set()
        self._outcomes: list[RequestOutcome] = []
        self._records: list[Record] = []
        self._next_sweep: Optional[float] = None
        self._sweep_open_until: Optional[float] = None
        self._sweep_names: set[int] = set()
        self._last_sweep: Optional[set[int]] = None
        self.first_sweep_done = False
        self.sweeps = 0
        self.sweeps_logged = 0

    # -- scheduling ---------------------------------------------------------------

    def _enqueue(self, pgn: int, da: int, conn: Optional[int] = None) -> None:
        if pgn not in self._allow:
            return  # never asks for anything outside the request allow-list (NP-9)
        key = (pgn, da)
        if key in self._failed or (key in self._asked and pgn != PGN_CLAIM):
            return  # NP-14: a failed request is not repeated; identity is asked once
        self._asked.add(key)
        self._queue.setdefault(da, deque()).append(_Pending(pgn, da, conn))

    def session_start(self) -> None:
        """Sweep, Time/Date and VIN at the start of a session (NP-11, NP-12)."""
        self._enqueue(PGN_CLAIM, GLOBAL)
        self._enqueue(PGN_TIME_DATE, self._vin_sa)
        self._enqueue(PGN_VIN, self._vin_sa)
        self._next_sweep = self._clock.mono() + self._interval

    def identify(self, conn: int, sa: int, name: Optional[int]) -> None:
        """Identity requests for a new connection, unless its NAME is known (NP-13)."""
        if name is not None and (name in self._known or name == self._logger_name):
            return
        for pgn in IDENTITY:
            self._enqueue(pgn, sa, conn)

    def poll(self) -> list[TxRequest]:
        """Timers and the next request for each free destination; returns what to send."""
        now = self._clock.mono()
        self._check_timeouts(now)
        self._close_sweep(now)
        if self._next_sweep is not None and now >= self._next_sweep:
            self._next_sweep = now + self._interval
            self._asked.discard((PGN_CLAIM, GLOBAL))
            self._enqueue(PGN_CLAIM, GLOBAL)
        out = []
        for da, queue in self._queue.items():
            if da in self._active or not queue:
                continue
            p = queue.popleft()
            out.append(self._send(p, now))
        return out

    def _send(self, p: _Pending, now: float) -> TxRequest:
        p.attempt += 1
        p.sent_mono = now
        if p.attempt == 1:
            p.first_sent_mono = now
        self._active[p.da] = p
        if p.pgn == PGN_CLAIM and p.da == GLOBAL:
            self._sweep_open_until = now + self._timeout
            self._sweep_names = set()
        return TxRequest(PGN_REQUEST, p.da, p.pgn.to_bytes(3, "little"), "request")

    def _finish(self, p: _Pending, outcome: str, value: Optional[bytes]) -> None:
        self._active.pop(p.da, None)
        self._release(p.da)
        if outcome != "reply":
            self._failed.add((p.pgn, p.da))
        if p.pgn != PGN_CLAIM:
            self._outcomes.append(
                RequestOutcome(p.conn, p.pgn, p.da, outcome, value, p.attempt, p.first_sent_mono)
            )

    def _check_timeouts(self, now: float) -> None:
        for p in list(self._active.values()):
            if now - p.sent_mono < self._timeout:
                continue
            if p.pgn == PGN_CLAIM and p.da == GLOBAL:
                self._active.pop(p.da, None)
                self._release(p.da)  # a sweep has no single reply: it closes on time
                continue
            if p.attempt <= self._retries:
                self._active.pop(p.da, None)
                self._release(p.da)
                self._queue.setdefault(p.da, deque()).appendleft(p)  # retry (NP-14)
            else:
                self._finish(p, "no reply", None)

    # -- replies --------------------------------------------------------------------

    def on_message(self, msg: J1939Msg, logger_sa: Optional[int]) -> None:
        if msg.own:
            return
        if msg.pgn == PGN_CLAIM and len(msg.data) == 8 and self._sweep_open_until is not None:
            self._sweep_names.add(int.from_bytes(msg.data, "little"))
            return
        if msg.pgn == PGN_ACK and len(msg.data) == 8 and msg.data[0] == 1:
            pgn = msg.data[5] | (msg.data[6] << 8) | (msg.data[7] << 16)
            p = self._active.get(msg.sa)
            if (
                p is not None
                and p.pgn == pgn
                and (logger_sa is None or msg.data[4] in (logger_sa, 0xFF))
            ):
                self._finish(p, "NACK", None)
            return
        p = self._active.get(msg.sa)
        if p is not None and p.pgn == msg.pgn and msg.da in (GLOBAL, logger_sa):
            self._finish(p, "reply", bytes(msg.data))

    # -- sweeps (LOG-9) ------------------------------------------------------------------

    def _close_sweep(self, now: float) -> None:
        if self._sweep_open_until is None or now < self._sweep_open_until:
            return
        self._sweep_open_until = None
        self.sweeps += 1
        names = self._sweep_names - {self._logger_name}
        first = self._last_sweep is None
        added = sorted(names - (self._last_sweep or set()))
        missing = sorted((self._last_sweep or set()) - names)
        if first or added or missing:
            self.sweeps_logged += 1
            self._records.append(
                Record(
                    type="sweep",
                    sev="notice" if (not first and (added or missing)) else "info",
                    utc=self._clock.to_utc(now),
                    veh_time=None,
                    fields={
                        "first": first,
                        "names": [f"0x{n:016X}" for n in sorted(names)],
                        "in_inventory": sum(1 for n in names if n in self._known),
                        "logger": f"0x{self._logger_name:016X}",
                        "added": [] if first else [f"0x{n:016X}" for n in added],
                        "missing": [] if first else [f"0x{n:016X}" for n in missing],
                    },
                )
            )
        self._last_sweep = names
        self.first_sweep_done = True

    # -- results --------------------------------------------------------------------------

    def take_outcomes(self) -> list[RequestOutcome]:
        out, self._outcomes = self._outcomes, []
        return out

    def take_records(self) -> list[Record]:
        out, self._records = self._records, []
        return out
