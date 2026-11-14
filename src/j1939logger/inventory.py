"""inventory: the known-good devices for this truck (docs/modules.md section 4, v1, step 6).

Layer 3: pure. No I/O and no clock; ``session`` gives times and writes each new
version through ``store``. Built to DC-20. Inventory files are ``inv-1``
dicts; ``config.validate_inventory`` turns one into the read-only
``config.Inventory`` that detection uses.

* ``Training``: observes every NAME, and every address that sends without
  claiming, between ``train_start`` and ``train_finish`` or until
  ``training.timeout_min`` (TRN-2, TRN-3): addresses, PGNs sent, the
  conditions each was heard in, identity replies. ``coverage()`` is the
  TRN-12 summary and ``propose()`` the proposed inventory.
* ``condition()``: the TRN-12 condition from EEC1, CCVS and PTO1.
* ``approve()``, ``remove()``, ``confirm_record()``, ``rejection_record()``:
  operator changes, each a new version (``next_version``) with entry IDs that
  are never reused (``next_entry_id``). Every change applies from the next
  session. Nothing is ever added automatically (TRN-11).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from j1939logger.decode import PGN_ADDRESS_CLAIM, PGN_ETP_DT, decode_name
from j1939logger.types import J1939Msg, Record

__all__ = [
    "Training",
    "condition",
    "next_version",
    "next_entry_id",
    "approve",
    "remove",
    "confirm_record",
    "rejection_record",
    "InventoryRefused",
    "PGN_EEC1",
    "PGN_CCVS",
    "PGN_PTO1",
]

BASELINE = "vehicle ECU in baseline"
APPROVED = "external device (approved)"
PGN_EEC1 = 61444
PGN_CCVS = 65265
PGN_PTO1 = 65264
PGN_COMPONENT_ID, PGN_SOFTWARE_ID, PGN_ECU_ID = 65259, 65242, 64965
NOT_AVAILABLE = 0xFAFF  # J1939 two-byte values above this are error or not available
NULL_SA, GLOBAL_SA = 254, 255
_ENTRY_ID = re.compile(r"^E(\d+)$")


class InventoryRefused(ValueError):
    """An operator change the inventory refuses, with the reason for the laptop."""


def reply_text(pgn: int, value: Optional[bytes]) -> Optional[str]:
    """Reply text without its trailing ``*``, as in identify (DC-17); siblings don't import."""
    if value is None:
        return None
    raw = value[1:] if pgn == PGN_SOFTWARE_ID and value else value
    return raw.decode("ascii", "replace").rstrip("\x00\xff\ufffd ").rstrip("*")


# -- conditions (TRN-12) -----------------------------------------------------


def _u16(data: bytes, i: int) -> Optional[int]:
    if len(data) < i + 2:
        return None
    v = data[i] | (data[i + 1] << 8)
    return None if v > NOT_AVAILABLE else v


def condition(
    rpm: Optional[float],
    kmh: Optional[float],
    pto: bool,
    labels: Sequence[str],
    engine_running_rpm: float,
    driving_kmh: float,
) -> str:
    """The condition label from ``training.states`` (key-on engine off, idle, driving, PTO)."""

    def label(i: int, default: str) -> str:
        return labels[i] if len(labels) > i else default

    if pto:
        return label(3, "PTO")
    if rpm is None or rpm < engine_running_rpm:
        return label(0, "key-on engine off")
    if kmh is not None and kmh >= driving_kmh:
        return label(2, "driving")
    return label(1, "idle")


# -- training (TRN-2, TRN-3, TRN-12) -----------------------------------------


@dataclass
class _Seen:
    name: Optional[int]
    addresses: set[int] = field(default_factory=set)
    pgns: set[int] = field(default_factory=set)
    states: list[str] = field(default_factory=list)
    pgns_by_state: dict[str, set[int]] = field(default_factory=dict)
    replies: dict[int, Optional[str]] = field(default_factory=dict)


class Training:
    def __init__(
        self,
        settings: Mapping[str, Any],
        start_mono: float,
        logger_name: int,
        operator: str,
    ) -> None:
        self.operator = operator
        self.start_mono = start_mono
        self._timeout_s = float(settings["training.timeout_min"]) * 60.0
        self._labels = list(settings["training.states"])
        self._rpm_on = float(settings["training.engine_running_rpm"])
        self._kmh_on = float(settings["training.driving_kmh"])
        self._logger_name = logger_name
        self._rpm: Optional[float] = None
        self._kmh: Optional[float] = None
        self._pto = False
        self._seen: dict[tuple[str, int], _Seen] = {}
        self._name_at: dict[int, int] = {}
        self.conditions: list[str] = []
        self.timed_out = False
        self.stopped = False

    @property
    def current_condition(self) -> str:
        return condition(self._rpm, self._kmh, self._pto, self._labels, self._rpm_on, self._kmh_on)

    def observing(self, now_mono: float) -> bool:
        """False once training finished or ``training.timeout_min`` passed (TRN-3)."""
        if not self.stopped and now_mono - self.start_mono >= self._timeout_s:
            self.stopped = self.timed_out = True
        return not self.stopped

    def observe(self, msg: J1939Msg) -> None:
        """Record one message from the bus (the logger's own frames are not observed)."""
        if msg.own or not self.observing(msg.ts_mono):
            return
        self._vehicle_state(msg)
        state = self.current_condition
        if state not in self.conditions:
            self.conditions.append(state)
        if msg.sa >= NULL_SA:
            return
        if msg.pgn == PGN_ADDRESS_CLAIM and len(msg.data) == 8:
            name = int.from_bytes(msg.data, "little")
            if name == self._logger_name:
                return  # the logger is never part of the inventory (TRN-14(c))
            self._name_at[msg.sa] = name
            sa_only = self._seen.pop(("sa", msg.sa), None)
            seen = self._seen.setdefault(("name", name), _Seen(name))
            if sa_only is not None:  # it claimed after sending: one entry
                seen.pgns |= sa_only.pgns
                for st in sa_only.states:
                    if st not in seen.states:
                        seen.states.append(st)
            seen.addresses.add(msg.sa)
            self._note(seen, state)
            return
        seen = self._entry(msg.sa)
        seen.addresses.add(msg.sa)
        if msg.pgn != PGN_ETP_DT:
            seen.pgns.add(msg.pgn)
            seen.pgns_by_state.setdefault(state, set()).add(msg.pgn)
        self._note(seen, state)

    def _entry(self, sa: int) -> _Seen:
        name = self._name_at.get(sa)
        if name is not None:
            return self._seen.setdefault(("name", name), _Seen(name))
        return self._seen.setdefault(("sa", sa), _Seen(None))

    @staticmethod
    def _note(seen: _Seen, state: str) -> None:
        if state not in seen.states:
            seen.states.append(state)

    def _vehicle_state(self, msg: J1939Msg) -> None:
        if msg.pgn == PGN_EEC1:
            raw = _u16(msg.data, 3)
            if raw is not None:
                self._rpm = raw * 0.125
        elif msg.pgn == PGN_CCVS:
            raw = _u16(msg.data, 1)
            if raw is not None:
                self._kmh = raw / 256.0
        elif msg.pgn == PGN_PTO1:
            raw = _u16(msg.data, 1)
            if raw is not None:
                self._pto = raw > 0

    def identity(self, sa: int, pgn: int, outcome: str, value: Optional[bytes]) -> None:
        """An identity reply from ``sa`` (NP-13: every device is asked during training)."""
        if self.stopped or sa >= NULL_SA:
            return
        self._entry(sa).replies[pgn] = reply_text(pgn, value) if outcome == "reply" else None

    def coverage(self, pto_declared: bool = False) -> dict[str, Any]:
        """Conditions seen and the PGNs per ECU in each (TRN-12)."""
        conditions = list(self.conditions)
        pto = self._labels[3] if len(self._labels) > 3 else "PTO"
        if pto_declared and pto not in conditions:
            conditions.append(pto)
        per_ecu = []
        for _key, seen in sorted(self._seen.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            per_ecu.append(
                {
                    "name": _hex(seen.name),
                    "addresses": sorted(seen.addresses),
                    "pgns": {st: sorted(p) for st, p in seen.pgns_by_state.items()},
                }
            )
        missing = [s for s in self._labels if s not in conditions]
        return {"conditions": conditions, "missing": missing, "pgns_per_ecu": per_ecu}

    def propose(
        self,
        *,
        previous: Optional[Mapping[str, Any]],
        stored: Iterable[Mapping[str, Any]],
        version: str,
        vin: Optional[str],
        session: int,
        now_utc: Optional[str],
        manufacturers: Optional[Mapping[str, str]] = None,
        pto_declared: bool = False,
    ) -> dict[str, Any]:
        """The proposed inventory (DC-20 item 4), not applied until confirmed (TRN-4)."""
        stored = list(stored)
        old = {e.get("name"): e for e in (previous or {}).get("entries", []) if e.get("name")}
        next_id = next_entry_id(stored)
        pto = self._labels[3] if len(self._labels) > 3 else "PTO"
        entries = []
        for _key, seen in sorted(self._seen.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            name = _hex(seen.name)
            prior = old.get(name) if name else None
            if prior is not None:
                entry_id = str(prior["entry"])
            else:
                entry_id, next_id = f"E{next_id:02d}", next_id + 1
            states = list(seen.states)
            if pto_declared and pto not in states:
                states.append(pto)
            entries.append(
                {
                    "entry": entry_id,
                    "name": name,
                    "name_fields": _name_fields(seen.name),
                    "make": _make(seen, manufacturers),
                    "category": BASELINE,
                    "addresses": sorted(seen.addresses),
                    "states_seen": states,
                    "self_reported": {
                        "component_id": seen.replies.get(PGN_COMPONENT_ID),
                        "software_id": seen.replies.get(PGN_SOFTWARE_ID),
                        "ecu_id": seen.replies.get(PGN_ECU_ID),
                    },
                    "pgns_sent": sorted(seen.pgns),
                    "pgns_approved": list(prior.get("pgns_approved", [])) if prior else [],
                    "added": {"how": "training", "inventory": version, "utc": now_utc},
                    "model": None,
                }
            )
        seen_names = {e["name"] for e in entries if e["name"]}
        for e in (previous or {}).get("entries", []):  # approved devices stay approved
            if e.get("category") == APPROVED and e.get("name") not in seen_names:
                entries.append(copy.deepcopy(dict(e)))
        return {
            "format": "inv-1",
            "inventory": version,
            "vin": vin if vin is not None else (previous or {}).get("vin"),
            "created_utc": now_utc,
            "previous": (previous or {}).get("inventory"),
            "change": f"trained in session {session}",
            "operator": self.operator,
            "source_session": session,
            "vehicle": copy.deepcopy((previous or {}).get("vehicle"))
            or {"make": None, "model": None, "year": None, "engine": None, "software_level": None},
            "entries": entries,
        }


def _hex(name: Optional[int]) -> Optional[str]:
    return None if name is None else f"0x{name:016X}"


def _name_fields(name: Optional[int]) -> Optional[dict[str, Any]]:
    if name is None:
        return None
    n = decode_name(name)
    return {
        "aac": n.aac,
        "industry_group": n.industry_group,
        "vehicle_system": n.vehicle_system,
        "function": n.function,
        "function_instance": n.function_instance,
        "ecu_instance": n.ecu_instance,
        "mfr_code": n.mfr_code,
        "identity": f"0x{n.identity:05X}",
    }


def _make(seen: _Seen, manufacturers: Optional[Mapping[str, str]]) -> str:
    component = (seen.replies.get(PGN_COMPONENT_ID) or "").split("*")
    if component and component[0].strip():
        return component[0].strip()
    if seen.name is None:
        return "unknown (no NAME)"
    code = decode_name(seen.name).mfr_code
    if manufacturers:
        return manufacturers.get(str(code)) or f"unknown (mfr code {code} not in the list)"
    return f"unknown (mfr code {code}; no manufacturer list loaded)"


# -- versions and entry IDs (TRN-6, TRN-14) ----------------------------------


def next_version(versions: Iterable[int]) -> str:
    """The next inventory version name, ``inv-vN+1``."""
    return f"inv-v{max(list(versions) or [0]) + 1}"


def next_entry_id(stored: Iterable[Mapping[str, Any]]) -> int:
    """One more than the highest entry ID in any stored version: IDs are never reused."""
    best = 0
    for inv in stored:
        for e in inv.get("entries", []) if isinstance(inv, Mapping) else []:
            m = _ENTRY_ID.match(str(e.get("entry", "")))
            if m:
                best = max(best, int(m.group(1)))
    return best + 1


def _new_version(
    inv: Mapping[str, Any],
    version: str,
    change: str,
    operator: str,
    session: int,
    now: Optional[str],
) -> dict[str, Any]:
    out = copy.deepcopy(dict(inv))
    out.update(
        {
            "inventory": version,
            "previous": inv.get("inventory"),
            "change": change,
            "operator": operator,
            "source_session": session,
            "created_utc": now,
        }
    )
    return out


def _record(rtype: str, fields: dict[str, Any]) -> Record:
    return Record(rtype, "notice", None, None, fields)


def confirm_record(proposal: Mapping[str, Any], operator: str, reason: Optional[str]) -> Record:
    """``approval`` of kind "inventory" for a confirmed training (TRN-4)."""
    return _record(
        "approval",
        {
            "operator": operator,
            "kind": "inventory",
            "pgn": None,
            "control_warning_shown": False,
            "entries": [e["entry"] for e in proposal.get("entries", [])],
            "new_inventory": proposal.get("inventory"),
            "reason": reason,
            "events_cleared": [],
        },
    )


def rejection_record(proposal: Mapping[str, Any], operator: str, reason: Optional[str]) -> Record:
    """``rejection`` of a proposed inventory; nothing is applied (TRN-4)."""
    return _record(
        "rejection",
        {
            "operator": operator,
            "kind": "inventory",
            "proposed_inventory": proposal.get("inventory"),
            "reason": reason,
        },
    )


# -- approvals (TRN-5, TRN-10) -----------------------------------------------


def _requested_from(end: Optional[Mapping[str, Any]]) -> list[int]:
    out = set()
    for item in (end or {}).get("requests_first_100", []):
        head = str(item).split(" ", 1)[0]
        if head.isdigit():
            out.add(int(head))
    return sorted(out)


def _find(inv: Mapping[str, Any], entry_id: str) -> dict[str, Any]:
    for e in inv.get("entries", []):
        if e.get("entry") == entry_id:
            return dict(e)
    raise InventoryRefused(f"no entry {entry_id} in {inv.get('inventory')}")


def approve(
    inv: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    event_id: str,
    end: Optional[Mapping[str, Any]] = None,
    stored: Iterable[Mapping[str, Any]] = (),
    version: str,
    operator: str,
    reason: str,
    session: int,
    now_utc: Optional[str],
    warning_shown: bool = False,
    control_pgns: Iterable[int] = (),
) -> tuple[dict[str, Any], Record]:
    """A new inventory version and its ``approval`` record from a logged event (DC-20)."""
    rtype = event.get("type")
    out = _new_version(inv, version, "", operator, session, now_utc)
    entries: list[dict[str, Any]] = [dict(e) for e in out.get("entries", [])]
    pgn: Optional[int] = None
    if rtype == "connection_start":
        kind = "device"
        name = event.get("name")
        sa = event.get("sa")
        if name is not None and any(e.get("name") == name for e in entries):
            raise InventoryRefused(f"NAME {name} is already in the inventory")
        if name is None and any(
            e.get("name") is None and sa in e.get("addresses", []) for e in entries
        ):
            raise InventoryRefused(f"SA {sa} is already in the inventory")
        entry_id = f"E{next_entry_id([inv, *stored]):02d}"
        sent = sorted({int(p["pgn"]) for p in (end or {}).get("pgns_sent", [])})
        entries.append(
            {
                "entry": entry_id,
                "name": name,
                "name_fields": event.get("name_fields"),
                "make": "unknown (approved from a logged connection)",
                "category": APPROVED,
                "addresses": [sa],
                "states_seen": [],
                "self_reported": {"component_id": None, "software_id": None, "ecu_id": None},
                "pgns_sent": sent,
                "pgns_approved": [],
                "added": {
                    "how": "approval",
                    "inventory": version,
                    "utc": now_utc,
                    "from_event": event_id,
                    "operator": operator,
                },  # fmt: skip
                "requests_trained": _requested_from(end),
                "model": None,
            }
        )
        affected = [entry_id]
        change = f"approved device added: SA {sa} ({entry_id})"
    elif rtype == "known_device_new_pgn":
        direction = event.get("direction")
        kind = "PGN sent" if direction == "sent" else "PGN requested"
        pgn = int(event["pgn"])
        entry = _find(out, str(event.get("entry")))
        approved = list(entry.get("pgns_approved", []))
        if any(a.get("pgn") == pgn and a.get("kind") == kind for a in approved):
            raise InventoryRefused(f"PGN {pgn} is already approved for {entry['entry']}")
        approved.append({"pgn": pgn, "kind": kind, "reason": reason, "utc": now_utc,
                         "operator": operator, "from_event": event_id})  # fmt: skip
        entry["pgns_approved"] = approved
        entries = [entry if e.get("entry") == entry["entry"] else e for e in entries]
        affected = [entry["entry"]]
        change = f"approved {kind} {pgn} for {entry['entry']}"
    elif rtype == "address_change" and event.get("sev") == "notice":
        kind = "address"
        entry = _find(out, str(event.get("entry")))
        new_sa = int(event["new_sa"])
        if new_sa in entry.get("addresses", []):
            raise InventoryRefused(f"SA {new_sa} is already an address of {entry['entry']}")
        entry["addresses"] = sorted({*entry.get("addresses", []), new_sa})
        entries = [entry if e.get("entry") == entry["entry"] else e for e in entries]
        affected = [entry["entry"]]
        change = f"approved address {new_sa} for {entry['entry']}"
    else:
        raise InventoryRefused(f"event {event_id} ({rtype}) cannot be approved")
    out["entries"] = entries
    out["change"] = change
    record = _record(
        "approval",
        {
            "operator": operator,
            "kind": kind,
            "pgn": pgn,
            "control_warning_shown": bool(warning_shown and pgn in set(control_pgns)),
            "entries": affected,
            "new_inventory": version,
            "reason": reason,
            "events_cleared": [event_id],
        },
    )
    return out, record


# -- removals (TRN-14, TRN-15) -----------------------------------------------


def remove(
    inv: Mapping[str, Any],
    entry_id: str,
    *,
    version: str,
    operator: str,
    reason: str,
    session: int,
    now_utc: Optional[str],
    pgn: Optional[int] = None,
    direction: Optional[str] = None,
    warning_shown: bool = False,
) -> tuple[dict[str, Any], Record]:
    """A new version without the entry (or one of its PGNs) and its ``inventory_remove`` record."""
    if not reason:
        raise InventoryRefused("a reason is required")
    entry = _find(inv, entry_id)
    out = _new_version(inv, version, "", operator, session, now_utc)
    if pgn is None:
        out["entries"] = [e for e in out.get("entries", []) if e.get("entry") != entry_id]
        removed = "remove device"
        out["change"] = f"removed {entry_id}"
    else:
        if direction not in ("sent", "requested"):
            raise InventoryRefused("direction must be sent or requested")
        trained_key = "pgns_sent" if direction == "sent" else "requests_trained"
        kind = "PGN sent" if direction == "sent" else "PGN requested"
        trained = [p for p in entry.get(trained_key, []) if p != pgn]
        approved = [a for a in entry.get("pgns_approved", [])
                    if not (a.get("pgn") == pgn and a.get("kind") == kind)]  # fmt: skip
        if len(trained) == len(entry.get(trained_key, [])) and len(approved) == len(
            entry.get("pgns_approved", [])
        ):
            raise InventoryRefused(f"PGN {pgn} ({direction}) is not in {entry_id}")
        entry[trained_key] = trained
        entry["pgns_approved"] = approved
        out["entries"] = [entry if e.get("entry") == entry_id else e for e in out["entries"]]
        removed = f"remove {kind}"
        out["change"] = f"removed {kind} {pgn} from {entry_id}"
    record = _record(
        "inventory_remove",
        {
            "operator": operator,
            "entry": entry_id,
            "name": entry.get("name"),
            "removed": removed,
            "pgn": pgn,
            "reason": reason,
            "warning_shown": bool(warning_shown),
            "old_inventory": inv.get("inventory"),
            "new_inventory": version,
        },
    )
    return out, record
