"""monitor: what each connected device does (docs/modules.md section 4, v1, frozen for step 4).

Layer 3: no I/O; time only through ``clock``. ``detect`` calls
``on_message(msg, conn, entry)`` for every decoded message, with the
sender's open ``Connection`` (or None) and the sender's inventory entry (or
None), and takes the ``connection_end`` activity fields from
``summary(conn)`` (DC-13). Rules (DC-13, DC-14):

* Own frames and replies to the logger are not monitored (NP-15).
* For a connection, each distinct PGN sent is kept with first-seen, last-seen
  and count, up to ``limits.pgns_per_conn`` PGNs; messages with a PGN that no
  longer fits are counted in ``pgns_dropped`` (DET-7, DET-19). ETP.DT
  (50944) frames are not tabled. TP.CM and TP.DT never reach monitor: decode
  returns the reassembled message instead.
* Requests (59904): the first ``detection.requests_kept`` go in
  ``requests_first_100`` as ``"<pgn> <name> -> SA <n>"`` or ``"... -> global"``;
  the rest are counted in ``requests_dropped`` (DET-8).
* ``ecus_contacted``: ascending destinations of destination-specific messages.
* ``dm_types``: DM1, DM2, DM3 and DM11 when requested (or DM11 sent),
  DM14, DM15, DM16 and DM18 when sent; in first-seen order (DET-10).
* ETP transfers follow ETP.CM (51200): RTS (control 20) from the connection
  opens one per sender and destination; EOMA (23) from the destination
  completes it; Abort (255) from either side aborts it. One still open at
  the end is reported as aborted. At most ``limits.tp_sessions`` are open at
  once; further RTSs are ignored. ``memory_transfer`` is true when the
  connection also sent DM14 to DM16 (DET-10).
* Proprietary PGNs (61184, 65280 to 65535) are listed without interpreting
  their content (DET-11).
* Control PGNs (``detection.control_pgns``), sent or requested, by a
  connection, or by a known device outside its trained and approved PGNs:
  ``control_flag`` at the first occurrence per sender and PGN, with ``via``
  "single frame", "transport (BAM)", "transport (RTS/CTS)" or "requested",
  ``target_sa`` null for global, ``raw_capture`` null (``rawcap`` is step 6);
  the running count is in ``control_flags`` (DET-9).
* A known device (inventory entry) sending a PGN outside ``pgns_sent`` and its
  "PGN sent" approvals, or an approved external device requesting a PGN
  outside ``requests_trained`` and its "PGN requested" approvals:
  ``known_device_new_pgn`` (notice) once per session per NAME (or SA for a
  never-claiming entry), PGN and direction, when
  ``detection.known_device_new_pgn`` is on (DET-12). The PGN goes in the
  connection's ``new_pgns``.

For an approved external device, ``summary`` gives ``new_pgns`` only; the
start, end, duration and end reason come from ``detect`` (log-format).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from j1939logger.clock import Clock
from j1939logger.config import Inventory, InventoryEntry
from j1939logger.decode import PGN_ADDRESS_CLAIM, PGN_ETP_CM, PGN_ETP_DT, PGN_REQUEST
from j1939logger.eventlog import format_utc
from j1939logger.types import Connection, J1939Msg, Record

__all__ = ["Monitor", "PGN_NAMES", "is_proprietary"]

APPROVED = "external device (approved)"

# The logger's own short name table: names the specs already use, nothing from
# the SAE Digital Annex (CLAUDE.md rule 13).
PGN_NAMES: Mapping[int, str] = {
    0: "TSC1",
    256: "TC1",
    1024: "XBR",
    54272: "DM18",
    55040: "DM16",
    55296: "DM15",
    55552: "DM14",
    56832: "Reset",
    59392: "Acknowledgment",
    59904: "Request",
    60160: "TP.DT",
    60416: "TP.CM",
    60928: "Address Claim",
    61184: "Proprietary A",
    65226: "DM1",
    65227: "DM2",
    65228: "DM3",
    65235: "DM11",
    65240: "Commanded Address",
    65242: "Software ID",
    65254: "Time/Date",
    65259: "Component ID",
    65260: "VIN",
    64965: "ECU ID",
}

# Names used in control_flag and control_flags (as in the session 142 example).
CONTROL_NAMES: Mapping[int, str] = {
    0: "TSC1",
    256: "TC1",
    1024: "XBR",
    56832: "Reset",
    65235: "DM11 clear codes",
    65240: "Commanded Address",
}

DM_REQUESTED = {65226: "DM1", 65227: "DM2", 65228: "DM3", 65235: "DM11"}
DM_SENT = {65235: "DM11", 55552: "DM14", 55296: "DM15", 55040: "DM16", 54272: "DM18"}
MEMORY_PGNS = {55552, 55296, 55040}

ETP_RTS, ETP_EOMA, ETP_ABORT = 20, 23, 255


def is_proprietary(pgn: int) -> bool:
    """Proprietary A (61184) or Proprietary B (65280 to 65535), DET-11."""
    return pgn == 61184 or 65280 <= pgn <= 65535


def pgn_name(pgn: int) -> Optional[str]:
    return PGN_NAMES.get(pgn) or ("Proprietary B" if 65280 <= pgn <= 65535 else None)


def _named(pgn: int) -> str:
    name = pgn_name(pgn)
    return f"{pgn} {name}" if name else str(pgn)


def _dest(da: int) -> str:
    return "global" if da == 255 else f"SA {da}"


def _approved(entry: InventoryEntry, kind: str) -> set[int]:
    out = set()
    for a in entry.raw.get("pgns_approved") or ():
        if isinstance(a, Mapping) and a.get("kind") == kind and isinstance(a.get("pgn"), int):
            out.add(a["pgn"])
    return out


def _ints(v: Any) -> set[int]:
    return {x for x in v if isinstance(x, int)} if isinstance(v, (list, tuple)) else set()


@dataclass
class _Etp:
    sender: int
    destination: int
    pgn: int
    size: int
    result: Optional[str] = None  # None while open


@dataclass
class _Flag:
    pgn: int
    target_sa: Optional[int]
    first_mono: float
    count: int = 0


@dataclass
class _Activity:
    """Everything monitor keeps for one connection."""

    approved: bool
    pgns: dict[int, list[float]] = field(default_factory=dict)  # pgn -> [first, last, count]
    pgns_dropped: int = 0
    requests: list[str] = field(default_factory=list)
    requests_dropped: int = 0
    ecus: set[int] = field(default_factory=set)
    dm_types: list[str] = field(default_factory=list)
    memory_activity: bool = False
    etp: list[_Etp] = field(default_factory=list)
    proprietary: set[int] = field(default_factory=set)
    new_pgns: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[int, _Flag] = field(default_factory=dict)  # control PGN -> flag


class Monitor:
    def __init__(
        self, clock: Clock, settings: Mapping[str, Any], inventory: Optional[Inventory] = None
    ) -> None:
        self._clock = clock
        self._control = set(settings["detection.control_pgns"])
        self._requests_kept = int(settings["detection.requests_kept"])
        self._new_pgn_on = bool(settings["detection.known_device_new_pgn"])
        self._pgns_per_conn = int(settings["limits.pgns_per_conn"])
        self._tp_sessions = int(settings["limits.tp_sessions"])
        self._inventory = inventory
        self._act: dict[int, _Activity] = {}
        self._known_flags: dict[Any, dict[int, _Flag]] = {}  # known devices without a connection
        self._new_seen: set[tuple[Any, int, str]] = set()  # (sender key, pgn, direction)
        self._open_etp: dict[tuple[int, int], tuple[Optional[int], _Etp]] = {}

    # -- input ---------------------------------------------------------------

    def on_message(
        self, msg: J1939Msg, conn: Optional[Connection], entry: Optional[InventoryEntry] = None
    ) -> list[Record]:
        """Monitor one message from ``conn`` (or a known device, ``entry``); records out."""
        if msg.own or msg.reply_to_logger:
            return []  # NP-15
        out: list[Record] = []
        act = self._activity(conn, entry) if conn is not None else None
        requested = self._requested_pgn(msg)
        if msg.pgn == PGN_ETP_CM:
            self._etp(msg, conn)
        if act is not None:
            self._table(act, msg, requested)
        key = self._sender_key(msg, conn, entry)
        if entry is not None:
            out += self._new_pgn(msg, conn, entry, key, act, requested)
        out += self._control_flag(msg, conn, entry, key, requested)
        return out

    def _activity(self, conn: Connection, entry: Optional[InventoryEntry]) -> _Activity:
        act = self._act.get(conn.conn)
        if act is None:
            approved = conn.category == APPROVED or (
                entry is not None and entry.category == APPROVED
            )
            act = self._act[conn.conn] = _Activity(approved=approved)
        return act

    @staticmethod
    def _requested_pgn(msg: J1939Msg) -> Optional[int]:
        if msg.pgn != PGN_REQUEST or len(msg.data) < 3:
            return None
        return int.from_bytes(msg.data[:3], "little")

    @staticmethod
    def _sender_key(
        msg: J1939Msg, conn: Optional[Connection], entry: Optional[InventoryEntry]
    ) -> Any:
        if entry is not None:
            return ("name", entry.name) if entry.name is not None else ("sa", msg.sa)
        if conn is not None:
            return ("conn", conn.conn)
        return ("sa", msg.sa)

    def _table(self, act: _Activity, msg: J1939Msg, requested: Optional[int]) -> None:
        t = msg.ts_mono
        if msg.pgn != PGN_ETP_DT:
            row = act.pgns.get(msg.pgn)
            if row is not None:
                row[1] = t
                row[2] += 1
            elif len(act.pgns) < self._pgns_per_conn:
                act.pgns[msg.pgn] = [t, t, 1]
            else:
                act.pgns_dropped += 1  # DET-19
        if msg.da != 255:
            act.ecus.add(msg.da)
        if requested is not None:
            if len(act.requests) < self._requests_kept:
                act.requests.append(f"{_named(requested)} -> {_dest(msg.da)}")
            else:
                act.requests_dropped += 1  # DET-8
            dm = DM_REQUESTED.get(requested)
        else:
            dm = DM_SENT.get(msg.pgn)
        if dm is not None and dm not in act.dm_types:
            act.dm_types.append(dm)
        if msg.pgn in MEMORY_PGNS:
            act.memory_activity = True
        if is_proprietary(msg.pgn):
            act.proprietary.add(msg.pgn)

    def _etp(self, msg: J1939Msg, conn: Optional[Connection]) -> None:
        d = msg.data
        if len(d) < 8:
            return  # malformed; decode counts it
        control = d[0]
        pgn = int.from_bytes(d[5:8], "little")
        if control == ETP_RTS:
            if conn is None or msg.da == 255:
                return  # only transfers a connection sends are logged
            key = (msg.sa, msg.da)
            if key not in self._open_etp and len(self._open_etp) >= self._tp_sessions:
                return  # DET-19: bounded
            old = self._open_etp.pop(key, None)
            if old is not None:
                old[1].result = "aborted"  # replaced by a new RTS
            tr = _Etp(msg.sa, msg.da, pgn, int.from_bytes(d[1:5], "little"))
            self._activity(conn, None).etp.append(tr)
            self._open_etp[key] = (conn.conn, tr)
        elif control == ETP_EOMA:
            found = self._open_etp.pop((msg.da, msg.sa), None)  # EOMA comes from the receiver
            if found is not None:
                found[1].result = "completed"
        elif control == ETP_ABORT:
            for key in ((msg.sa, msg.da), (msg.da, msg.sa)):
                found = self._open_etp.pop(key, None)
                if found is not None:
                    found[1].result = "aborted"
                    break

    def _via(self, msg: J1939Msg, requested: Optional[int]) -> str:
        if requested is not None:
            return "requested"
        if not msg.via_tp:
            return "single frame"
        return "transport (BAM)" if msg.da == 255 else "transport (RTS/CTS)"

    def _known_sets(self, entry: InventoryEntry) -> tuple[set[int], set[int]]:
        sent = (
            set(entry.pgns_sent) | _ints(entry.raw.get("pgns_sent")) | _approved(entry, "PGN sent")
        )
        req = _ints(entry.raw.get("requests_trained")) | _approved(entry, "PGN requested")
        return sent, req

    def _control_flag(
        self,
        msg: J1939Msg,
        conn: Optional[Connection],
        entry: Optional[InventoryEntry],
        key: Any,
        requested: Optional[int],
    ) -> list[Record]:
        pgn = requested if requested is not None else msg.pgn
        if pgn not in self._control:
            return []
        if entry is not None and (conn is None or entry.category != APPROVED):
            sent, req = self._known_sets(entry)
            if pgn in (req if requested is not None else sent):
                return []  # trained or approved for this known device (DET-9)
        elif conn is None:
            return []  # neither a connection nor a known device
        target = None if msg.da == 255 else msg.da
        if conn is not None:
            flags = self._activity(conn, entry).flags  # per connection and PGN (DC-13)
        else:
            flags = self._known_flags.setdefault(key, {})
        flag = flags.get(pgn)
        if flag is not None:
            flag.count += 1
            return []
        flags[pgn] = _Flag(pgn, target, msg.ts_mono, 1)
        fields = {
            "sa": msg.sa,
            "pgn": pgn,
            "pgn_name": CONTROL_NAMES.get(pgn, pgn_name(pgn)),
            "target_sa": target,
            "via": self._via(msg, requested),
            "count": 1,
            "raw_capture": None,  # rawcap, step 6 (DC-14)
        }
        return [self._record("control_flag", "high", msg.ts_mono, fields, conn)]

    def _new_pgn(
        self,
        msg: J1939Msg,
        conn: Optional[Connection],
        entry: InventoryEntry,
        key: Any,
        act: Optional[_Activity],
        requested: Optional[int],
    ) -> list[Record]:
        if not self._new_pgn_on:
            return []
        sent, req = self._known_sets(entry)
        # The address claim is how the entry's NAME was learned, so training saw it.
        skip = msg.pgn in (PGN_ETP_DT, PGN_ADDRESS_CLAIM)
        checks = [] if skip else [(msg.pgn, "sent", sent)]
        if requested is not None and entry.category == APPROVED:
            checks.append((requested, "requested", req))
        out = []
        for pgn, direction, known in checks:
            if pgn in known or (key, pgn, direction) in self._new_seen:
                continue
            self._new_seen.add((key, pgn, direction))
            if act is not None:
                act.new_pgns.append({"pgn": pgn, "name": pgn_name(pgn), "direction": direction})
            fields = {
                "sa": msg.sa,
                "name": None if entry.name is None else f"0x{entry.name:016X}",
                "entry": entry.entry,
                "pgn": pgn,
                "pgn_name": pgn_name(pgn),
                "direction": direction,
                "count": 1,
            }
            out.append(self._record("known_device_new_pgn", "notice", msg.ts_mono, fields, conn))
        return out

    def _record(
        self,
        rtype: str,
        sev: str,
        t: float,
        fields: dict[str, Any],
        conn: Optional[Connection],
    ) -> Record:
        return Record(
            rtype,
            sev,
            self._clock.to_utc(t),
            self._clock.veh_time(t),
            fields,
            conn.conn if conn is not None else None,
        )

    # -- output --------------------------------------------------------------

    def summary(self, conn: int) -> dict[str, Any]:
        """The ``connection_end`` activity fields for connection ``conn`` (DC-13, DC-14)."""
        act = self._act.get(conn)
        if act is None:
            act = _Activity(approved=False)
        if act.approved:
            return {"new_pgns": list(act.new_pgns)}
        utc = self._clock.to_utc
        flags = [
            {
                "pgn": f.pgn,
                "name": CONTROL_NAMES.get(f.pgn, pgn_name(f.pgn)),
                "target_sa": f.target_sa,
                "first": format_utc(utc(f.first_mono)),
                "count": f.count,
            }
            for f in act.flags.values()
        ]
        return {
            "pgns_sent": [
                {
                    "pgn": pgn,
                    "name": pgn_name(pgn),
                    "first": format_utc(utc(row[0])),
                    "last": format_utc(utc(row[1])),
                    "count": int(row[2]),
                }
                for pgn, row in act.pgns.items()
            ],
            "pgns_dropped": act.pgns_dropped,
            "requests_first_100": list(act.requests),
            "requests_dropped": act.requests_dropped,
            "ecus_contacted": sorted(act.ecus),
            "dm_types": list(act.dm_types),
            "control_flags": flags,
            "etp_transfers": [
                {
                    "sender": e.sender,
                    "destination": e.destination,
                    "pgn": e.pgn,
                    "bytes": e.size,
                    "result": e.result or "aborted",
                    "memory_transfer": act.memory_activity,
                }
                for e in act.etp
            ],
            "proprietary_pgns": sorted(act.proprietary),
            "new_pgns": list(act.new_pgns),
        }

    def end(self, conn: int) -> dict[str, Any]:
        """``summary(conn)``, then forget the connection (its transfers close as aborted)."""
        out = self.summary(conn)
        self._act.pop(conn, None)
        for k in [k for k, (c, _) in self._open_etp.items() if c == conn]:
            del self._open_etp[k]
        return out

    @property
    def open_transfers(self) -> int:
        return len(self._open_etp)

    def table_sizes(self) -> Iterable[int]:
        """Distinct PGNs held per connection (for the DET-19 bound in tests)."""
        return [len(a.pgns) for a in self._act.values()]
