"""detect: when a device connects, moves or ends (docs/modules.md section 4, v1, frozen for step 4).

Layer 3: no I/O; time only through ``clock`` and each message's ``ts_mono``.
Built to DC-13; classification by wake timing stays here until ``identify``
(step 5).

``Detect(clock, settings, inventory, summary=None, ready_mono=None)``

* ``on_message(msg, logger_sa)`` returns ``connection_start``,
  ``address_conflict`` and the DET-2 and DET-3 starts that the first-sweep
  wait held back once it has ended.
* ``poll(now_mono)`` returns confirmed moves (``address_change``), the end of
  the wait when no sweep can be sent, and ``connection_end`` for silence.
* ``sweep_complete(mono)`` ends the first-sweep wait (sweep sent plus the
  request timeout, from ``requests``); ``no_sweep()`` says none can be sent this
  session, so the wait ends ``detection.first_sweep_wait_s`` after ready and
  inventory addresses stay as matches for the session (DET-2).
* ``end_all(reason)`` ends every open connection: "key-off" (DET-6), or
  another Connection end reason; the end time is each connection's last frame.
* ``connection_for(sa)`` and ``entry_for(sa)`` give ``monitor`` the sender's
  connection and inventory entry; ``name_at(sa)`` is the session's
  address-to-NAME map.

Rules:

* DET-1, DET-15: an address claim from a NAME that is not in the inventory
  opens a connection keyed by NAME; an approved external device gets the
  info short form (DET-17); a baseline ECU gets none (LOG-7). A non-claiming
  device that later claims keeps its connection, now keyed by NAME.
* DET-2: after the wait, traffic from an address no claimed NAME holds and no
  never-claiming entry owns opens a connection keyed by SA. During the wait
  such addresses are held, then decided when it ends; inventory addresses are
  provisional matches until then (and for the session when no sweep is sent).
* DET-3: a destination-specific message to an address no claimed NAME holds
  (not 254, 255, the logger's or a never-claiming inventory address) opens a
  connection keyed by that SA, trigger "replies sent to SA N".
* DET-4: two NAMEs at one address give ``address_conflict`` (notice, high if a
  known ECU loses its address). A NAME at a new, uncontested address gives
  ``address_change`` once the old address has been silent for
  ``detection.move_grace_s`` (info, notice if the address belongs to another
  known ECU), once per NAME and address per session. A frame from the old
  address within the grace, or after the move before another NAME claims it
  (which covers both answering a sweep), gives ``address_conflict`` "same NAME
  at two addresses", high, once per NAME and address pair per session.
* DET-6: a connection ends with "silence" when other frames arrive
  ``detection.silence_end_s`` after its last frame; a device returning after
  its connection ended starts a new connection (DET-15).
* NP-15: the logger's own frames and replies to it are ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional

from j1939logger.clock import Clock
from j1939logger.config import Inventory, InventoryEntry
from j1939logger.decode import PGN_ADDRESS_CLAIM, decode_name
from j1939logger.eventlog import format_utc
from j1939logger.types import Connection, J1939Msg, Name, Record

__all__ = ["Detect"]

APPROVED = "external device (approved)"
BASELINE = "vehicle ECU in baseline"
NOT_IN_BASELINE = "vehicle ECU not in baseline"
UNRECOGNIZED = "external device (unrecognized)"
NULL_SA, GLOBAL_SA = 254, 255

Summary = Callable[[int], Mapping[str, Any]]
# identify.classify bound to the session's settings (v1.2, DC-17):
# (NAME or None, seconds since the session's first frame, "first claim" | "first frame")
# -> (category, severity, classification_rule, classification_detail)
Classify = Callable[[Optional[Name], float, str], tuple[str, str, str, str]]


def _minutes_or_seconds(s: float) -> str:
    if s >= 60:
        return f"{s / 60:.0f} min"
    return f"{s:.1f} s"


def _hex(name: Optional[int]) -> Optional[str]:
    return None if name is None else f"0x{name:016X}"


@dataclass
class _Move:
    name: int
    old: int
    new: int
    claim_mono: float
    old_heard: bool = False  # a frame from the old address within the grace


class Detect:
    def __init__(
        self,
        clock: Clock,
        settings: Mapping[str, Any],
        inventory: Optional[Inventory],
        summary: Optional[Summary] = None,
        ready_mono: Optional[float] = None,
        classify: Optional[Classify] = None,
    ) -> None:
        self._clock = clock
        self._silence_s = float(settings["detection.silence_end_s"])
        self._grace_s = float(settings["detection.move_grace_s"])
        self._wait_s = float(settings["detection.first_sweep_wait_s"])
        self._wake_window_s = float(settings["classify.wake_window_s"])
        self._summary = summary
        self._classify_fn = classify
        self._untrained = inventory is None
        entries = inventory.entries if inventory is not None else ()
        self._by_name: dict[int, InventoryEntry] = {
            e.name: e for e in entries if e.name is not None
        }
        self._never_claims: dict[int, InventoryEntry] = {
            a: e for e in entries if e.name is None for a in e.addresses
        }
        self._hint: dict[int, InventoryEntry] = {  # inventory addresses: hints only (DET-2)
            a: e for e in entries if e.name is not None for a in e.addresses
        }
        self._ready_mono = ready_mono
        self._first_mono: Optional[float] = None
        self._last_bus: Optional[float] = None
        self._waiting = True  # first-sweep wait (DET-2)
        self._no_sweep = False
        self._held: dict[int, tuple[J1939Msg, str]] = {}  # SA -> first message, trigger
        self._name_at: dict[int, int] = {}  # SA -> NAME claimed this session
        self._sa_of: dict[int, int] = {}  # NAME -> its current SA
        self._last_from: dict[int, float] = {}  # SA -> last frame
        self._open: dict[tuple[str, int], Connection] = {}
        self._sev: dict[int, str] = {}
        self._entry_of: dict[int, Optional[InventoryEntry]] = {}
        self._moves: list[_Move] = []
        self._moved_from: dict[int, int] = {}  # old SA -> NAME that moved away
        self._changes_logged: set[tuple[int, int]] = set()
        self._conflicts_logged: set[tuple[int, int, int]] = set()
        self._next_conn = 1

    # -- queries -------------------------------------------------------------

    @property
    def connections(self) -> list[Connection]:
        return list(self._open.values())

    @property
    def waiting(self) -> bool:
        return self._waiting

    def name_at(self, sa: int) -> Optional[int]:
        return self._name_at.get(sa)

    def connection_for(self, sa: int) -> Optional[Connection]:
        name = self._name_at.get(sa)
        if name is not None and ("name", name) in self._open:
            return self._open[("name", name)]
        return self._open.get(("sa", sa))

    def entry_for(self, sa: int) -> Optional[InventoryEntry]:
        """The inventory entry for the device at ``sa`` this session, or None."""
        name = self._name_at.get(sa)
        if name is not None:
            return self._by_name.get(name)
        if sa in self._never_claims:
            return self._never_claims[sa]
        if self._provisional():
            return self._hint.get(sa)
        return None

    def _provisional(self) -> bool:
        return self._waiting or self._no_sweep

    # -- first-sweep wait ----------------------------------------------------

    def sweep_complete(self, mono: float) -> list[Record]:
        """The first sweep is over (sent plus the request timeout): decide held addresses."""
        if not self._waiting:
            return []
        self._waiting = False
        return self._decide_held(mono)

    def no_sweep(self) -> None:
        """No sweep can be sent this session; the wait ends at ready + first_sweep_wait_s."""
        self._no_sweep = True

    def _decide_held(self, mono: float) -> list[Record]:
        out = []
        held, self._held = self._held, {}
        for sa, (msg, trigger) in sorted(held.items()):
            if self._unclaimed(sa):
                out += self._start_sa(msg, sa, trigger, at_mono=mono)
        return out

    def _unclaimed(self, sa: int) -> bool:
        """No claimed NAME and no never-claiming entry holds ``sa`` (DET-2, DET-3)."""
        if sa in self._name_at or sa in self._never_claims or sa >= NULL_SA:
            return False
        if sa in self._moved_from or any(mv.old == sa for mv in self._moves):
            return False  # a NAME's old address: DET-4 handles it

        if self._provisional() and sa in self._hint:
            return False
        return True

    # -- messages ------------------------------------------------------------

    def on_message(self, msg: J1939Msg, logger_sa: Optional[int] = None) -> list[Record]:
        if msg.own:
            return []  # NP-15
        t = msg.ts_mono
        if self._first_mono is None:
            self._first_mono = t
        if self._ready_mono is None:
            self._ready_mono = t
        self._last_bus = t if self._last_bus is None else max(self._last_bus, t)
        out: list[Record] = []
        out += self._old_address_heard(msg)
        self._last_from[msg.sa] = t
        if msg.pgn == PGN_ADDRESS_CLAIM and len(msg.data) == 8:
            out += self._claim(msg, int.from_bytes(msg.data, "little"), logger_sa)
        elif msg.sa < NULL_SA:
            out += self._traffic(msg)
        if not msg.reply_to_logger and msg.da not in (NULL_SA, GLOBAL_SA, logger_sa):
            out += self._reply_to(msg)
        return out

    def _traffic(self, msg: J1939Msg) -> list[Record]:
        conn = self.connection_for(msg.sa)
        if conn is not None:
            conn.last_mono = msg.ts_mono
            return []
        name = self._name_at.get(msg.sa)
        if name is not None:
            entry = self._by_name.get(name)
            if entry is None or entry.category == APPROVED:  # returning device (DET-15)
                return [self._start_name(msg, name, entry, "returned after connection end")]
            return []
        entry = self._never_claims.get(msg.sa)
        if entry is not None:
            if entry.category == APPROVED:
                return self._start_sa(msg, msg.sa, "approved device without address claim")
            return []
        return self._unclaimed_sa(msg, msg.sa, "traffic without an address claim")

    def _reply_to(self, msg: J1939Msg) -> list[Record]:
        da = msg.da
        if self.connection_for(da) is not None or da in self._name_at:
            return []
        return self._unclaimed_sa(msg, da, f"replies sent to SA {da}")  # DET-3

    def _unclaimed_sa(self, msg: J1939Msg, sa: int, trigger: str) -> list[Record]:
        if self._waiting:
            # held, inventory addresses included, and decided when the wait ends (DET-2)
            if sa not in self._name_at and sa not in self._never_claims and sa < NULL_SA:
                self._held.setdefault(sa, (msg, trigger))
            return []
        if not self._unclaimed(sa):
            return []
        return self._start_sa(msg, sa, trigger)

    # -- claims and moves (DET-1, DET-4, DET-15) -----------------------------

    def _claim(self, msg: J1939Msg, name: int, logger_sa: Optional[int]) -> list[Record]:
        sa, t = msg.sa, msg.ts_mono
        out: list[Record] = []
        if sa == NULL_SA:
            return out  # Cannot Claim
        if self._moved_from.get(sa) == name or any(
            mv.name == name and mv.old == sa for mv in self._moves
        ):
            return out  # the old address answering with the same NAME: a conflict, not a move
        holder = self._name_at.get(sa)
        if holder is not None and holder != name:
            if sa != logger_sa:  # the logger's own loss is address's record
                out.append(self._two_names(msg, holder, name))
            if holder < name:
                return out  # the lower NAME keeps the address
            self._sa_of.pop(holder, None)
        self._moved_from.pop(sa, None)  # another NAME now holds the old address
        prev = self._sa_of.get(name)
        entry = self._by_name.get(name)
        if prev is None and entry is not None and entry.addresses and sa not in entry.addresses:
            prev = entry.addresses[0]  # new compared with the inventory
        self._name_at[sa] = name
        self._sa_of[name] = sa
        if prev is not None and prev != sa:
            if self._name_at.get(prev) == name:
                del self._name_at[prev]
            self._moves.append(_Move(name, prev, sa, t))
        self._held.pop(sa, None)
        sa_conn = self._open.pop(("sa", sa), None)
        if sa_conn is not None:  # a non-claiming device now claims: same connection
            sa_conn.key, sa_conn.name, sa_conn.last_mono = ("name", name), decode_name(name), t
            self._open[("name", name)] = sa_conn
            return out
        conn = self._open.get(("name", name))
        if conn is not None:
            conn.last_mono, conn.sa = t, sa
            return out
        if entry is not None and entry.category != APPROVED:
            return out  # baseline ECU: no connection record (LOG-7)
        since = t - (self._first_mono if self._first_mono is not None else t)
        trigger = (
            "address claim at session start"
            if since <= self._wake_window_s
            else "new address claim during steady state"
        )
        out.append(self._start_name(msg, name, entry, trigger))
        return out

    def _two_names(self, msg: J1939Msg, holder: int, name: int) -> Record:
        winner = min(holder, name)
        loser = max(holder, name)
        known_lost = loser in self._by_name and self._by_name[loser].category == BASELINE
        fields = {
            "sa": msg.sa,
            "names": [_hex(holder), _hex(name)],
            "cause": "two NAMEs claimed the same address",
            "winner": _hex(winner),
            "logger_action": "none",
        }
        return self._record("address_conflict", "high" if known_lost else "notice", msg, fields)

    def _old_address_heard(self, msg: J1939Msg) -> list[Record]:
        """A frame from an address its NAME has moved away from (DET-4)."""
        sa = msg.sa
        for mv in self._moves:
            if mv.old == sa and msg.ts_mono >= mv.claim_mono:
                mv.old_heard = True
        name = self._moved_from.get(sa)
        if name is None or self._name_at.get(sa) not in (None, name):
            return []
        if msg.pgn == PGN_ADDRESS_CLAIM and msg.data != name.to_bytes(8, "little"):
            return []  # another NAME claims the old address
        return self._same_name(msg, name, sa, self._sa_of.get(name, sa))

    def _same_name(self, msg: J1939Msg, name: int, old: int, new: int) -> list[Record]:
        key = (name, min(old, new), max(old, new))
        if key in self._conflicts_logged:
            return []
        self._conflicts_logged.add(key)
        fields = {
            "sa": [old, new],
            "names": [_hex(name)],
            "cause": "same NAME at two addresses",
            "winner": None,
            "logger_action": "none",
        }
        return [self._record("address_conflict", "high", msg, fields)]

    def _confirm_moves(self, now: float) -> list[Record]:
        out: list[Record] = []
        keep = []
        for mv in self._moves:
            if self._sa_of.get(mv.name) != mv.new:
                continue  # superseded by a later claim
            if mv.old_heard:
                probe = J1939Msg(
                    now, 0.0, 6, PGN_ADDRESS_CLAIM, mv.old, 255, b"", False, False, False
                )
                out += self._same_name(probe, mv.name, mv.old, mv.new)
                self._moved_from[mv.old] = mv.name
                continue
            if now - mv.claim_mono < self._grace_s:
                keep.append(mv)
                continue
            self._moved_from[mv.old] = mv.name  # confirmed (DET-4)
            out += self._address_change(mv, now)
        self._moves = keep
        return out

    def _address_change(self, mv: _Move, now: float) -> list[Record]:
        entry = self._by_name.get(mv.name)
        if entry is None or (mv.name, mv.new) in self._changes_logged:
            return []
        self._changes_logged.add((mv.name, mv.new))
        other = self._hint.get(mv.new)
        sev = "notice" if other is not None and other.name != mv.name else "info"
        conn = self._open.get(("name", mv.name))
        fields: dict[str, Any] = {
            "name": _hex(mv.name),
            "entry": entry.entry,
            "old_sa": mv.old,
            "new_sa": mv.new,
        }
        if conn is not None:
            fields["conn"] = conn.conn
        return [
            Record(
                "address_change",
                sev,
                self._clock.to_utc(mv.claim_mono),
                self._clock.veh_time(mv.claim_mono),
                fields,
                conn.conn if conn is not None else None,
            )
        ]

    # -- starts --------------------------------------------------------------

    def _start_name(
        self, msg: J1939Msg, name: int, entry: Optional[InventoryEntry], trigger: str
    ) -> Record:
        decoded = decode_name(name)
        if entry is not None:  # approved external device: short form (DET-17)
            category, sev = APPROVED, "info"
            fields: dict[str, Any] = {
                "sa": msg.sa,
                "name": _hex(name),
                "trigger": trigger,
                "in_inventory": True,
                "entry": entry.entry,
                "category": category,
                "classification_rule": "in inventory",
            }
        else:
            category, sev, rule, detail = self._classify(msg.ts_mono, "first claim", decoded)
            fields = {
                "sa": msg.sa,
                "name": _hex(name),
                "name_fields": {
                    "aac": decoded.aac,
                    "industry_group": decoded.industry_group,
                    "vehicle_system": decoded.vehicle_system,
                    "function": decoded.function,
                    "function_instance": decoded.function_instance,
                    "ecu_instance": decoded.ecu_instance,
                    "mfr_code": decoded.mfr_code,
                    "identity": f"0x{decoded.identity:X}",
                },
                "trigger": trigger,
                "in_inventory": False,
                "category": category,
                "classification_rule": rule,
                "classification_detail": detail,
            }
        conn = self._new_conn(("name", name), msg.sa, decoded, msg.ts_mono, category, sev, entry)
        return self._record("connection_start", sev, msg, fields, conn)

    def _start_sa(
        self, msg: J1939Msg, sa: int, trigger: str, at_mono: Optional[float] = None
    ) -> list[Record]:
        if ("sa", sa) in self._open:
            return []
        entry = self._never_claims.get(sa)
        if entry is not None and entry.category == APPROVED:
            category, sev = APPROVED, "info"
            fields: dict[str, Any] = {
                "sa": sa,
                "name": None,
                "trigger": trigger,
                "in_inventory": True,
                "entry": entry.entry,
                "category": category,
                "classification_rule": "in inventory",
            }
        else:
            entry = None
            category, sev, rule, detail = self._classify(msg.ts_mono, "first frame")
            fields = {
                "sa": sa,
                "name": None,
                "trigger": trigger,
                "in_inventory": False,
                "category": category,
                "classification_rule": rule,
                "classification_detail": detail,
            }
        first = msg.ts_mono
        conn = self._new_conn(("sa", sa), sa, None, first, category, sev, entry)
        if at_mono is not None:
            conn.last_mono = max(conn.last_mono, self._last_from.get(sa, first))
        return [self._record("connection_start", sev, msg, fields, conn)]

    def _classify(
        self, t: float, what: str, name: Optional[Name] = None
    ) -> tuple[str, str, str, str]:
        """identify.classify when injected (DC-17); else wake timing (DET-13, TRN-9)."""
        since = t - (self._first_mono if self._first_mono is not None else t)
        if self._classify_fn is not None:
            return self._classify_fn(name, since, what)
        category = NOT_IN_BASELINE if since <= self._wake_window_s else UNRECOGNIZED
        sev = "notice" if self._untrained else "high"
        detail = f"{what} {_minutes_or_seconds(since)} after the session's first frame"
        return category, sev, "wake timing", detail

    def _new_conn(
        self,
        key: tuple[str, int],
        sa: int,
        name: Any,
        t: float,
        category: str,
        sev: str,
        entry: Optional[InventoryEntry],
    ) -> Connection:
        conn = Connection(self._next_conn, key, sa, name, t, t, category)
        self._next_conn += 1
        self._open[key] = conn
        self._sev[conn.conn] = sev
        self._entry_of[conn.conn] = entry
        return conn

    # -- ends (DET-6) --------------------------------------------------------

    def poll(self, now_mono: float) -> list[Record]:
        """Moves, the no-sweep wait end and silence ends, as of ``now_mono``."""
        out = self._confirm_moves(now_mono)
        if (
            self._waiting
            and self._no_sweep
            and self._ready_mono is not None
            and now_mono - self._ready_mono >= self._wait_s
        ):
            self._waiting = False
            out += self._decide_held(now_mono)
        if self._last_bus is not None:
            for conn in list(self._open.values()):
                if self._last_bus - conn.last_mono >= self._silence_s:
                    out.append(self._end(conn, "silence", self._last_bus))
        return out

    def end_all(self, reason: str, now_mono: Optional[float] = None) -> list[Record]:
        """End every open connection, for example at key-off (DET-6).

        Each end time is the connection's last frame; the record time is
        ``now_mono`` (when the end was decided), else the last frame on the bus.
        """
        now = now_mono if now_mono is not None else self._last_bus
        now = now if now is not None else 0.0
        return [self._end(c, reason, max(now, c.last_mono)) for c in list(self._open.values())]

    def _end(self, conn: Connection, reason: str, at: float) -> Record:
        self._open.pop(conn.key, None)
        entry = self._entry_of.pop(conn.conn, None)
        sev = self._sev.pop(conn.conn, "info")
        utc = self._clock.to_utc
        fields: dict[str, Any] = {"sa": conn.sa}
        if entry is not None:
            fields["entry"] = entry.entry
        fields.update(
            {
                "start": format_utc(utc(conn.start_mono)),
                "end": format_utc(utc(conn.last_mono)),
                "end_reason": reason,
                "duration_s": round(conn.last_mono - conn.start_mono, 1),
            }
        )
        activity = dict(self._summary(conn.conn)) if self._summary is not None else {}
        if conn.category == APPROVED:
            activity = {"new_pgns": activity.get("new_pgns", [])}
        fields.update(activity)
        return Record("connection_end", sev, utc(at), self._clock.veh_time(at), fields, conn.conn)

    def _record(
        self,
        rtype: str,
        sev: str,
        msg: J1939Msg,
        fields: dict[str, Any],
        conn: Optional[Connection] = None,
    ) -> Record:
        t = msg.ts_mono
        return Record(
            rtype,
            sev,
            self._clock.to_utc(t),
            self._clock.veh_time(t),
            fields,
            conn.conn if conn is not None else None,
        )
