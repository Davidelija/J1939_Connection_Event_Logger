"""identify: what kind of device it is (docs/modules.md section 4, v1, frozen for step 5).

Layer 3: pure. No I/O and no clock; record times come from the caller.
Built to DC-17 and DC-18.

* ``classify(name, since_first_frame_s, ...)``: the category at connection
  start. A trailer device (notice, rule "NAME") when the NAME's industry group
  is 1 (on-highway) and its vehicle system is ``classify.trailer_vehicle_system``
  (DET-18(a)); else wake timing: a vehicle ECU not in baseline within
  ``classify.wake_window_s`` of the session's first frame, otherwise an
  unrecognized external device (DET-13). High, capped at notice when untrained.
* ``reclassify(category, ...)``: the DET-13 and DET-18(c) reason, if any, that
  makes a not-in-baseline or trailer device an unrecognized external device.
* ``identify(conn, outcomes, requested, library, ...)``: rules first, then the
  IDN-4 score; make and model by IDN-3 precedence; confidence from the number
  of agreeing sources (DC-17).
* ``identification_fields(ident, outcomes, to_utc)`` and
  ``identification_record(conn, ident, outcomes, to_utc)``: the
  ``identification`` record (also ``final_identification`` at connection end).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from j1939logger.config import Library
from j1939logger.eventlog import format_utc
from j1939logger.types import Connection, Name, Record

__all__ = [
    "Identification",
    "classify",
    "reclassify",
    "identify",
    "identification_fields",
    "identification_record",
    "reply_text",
    "MEMORY_PGNS",
]

APPROVED = "external device (approved)"
NOT_IN_BASELINE = "vehicle ECU not in baseline"
TRAILER = "trailer device"
UNRECOGNIZED = "external device (unrecognized)"
ON_HIGHWAY = 1

PGN_CLAIM = 60928
PGN_COMPONENT_ID = 65259
PGN_SOFTWARE_ID = 65242
PGN_ECU_ID = 64965
REQUEST_NAMES = {
    PGN_COMPONENT_ID: "Component ID",
    PGN_SOFTWARE_ID: "Software ID",
    PGN_ECU_ID: "ECU ID",
}
MEMORY_PGNS = frozenset({55552, 55296, 55040, 54784, 54272})  # DM14 to DM18

CONFIDENCE = ("low", "medium", "high")


def severity(category: str, untrained: bool) -> str:
    """The connection's severity by category (log-format severity rules, IDN-6)."""
    if category == APPROVED:
        return "info"
    sev = "notice" if category == TRAILER else "high"
    return "notice" if untrained else sev


def _since(s: float) -> str:
    return f"{s / 60:.0f} min" if s >= 60 else f"{s:.1f} s"


def classify(
    name: Optional[Name],
    since_first_frame_s: float,
    *,
    wake_window_s: float,
    trailer_vehicle_system: int,
    untrained: bool = False,
    what: str = "first claim",
) -> tuple[str, str, str, str]:
    """(category, severity, classification_rule, classification_detail) at start."""
    if (
        name is not None
        and name.industry_group == ON_HIGHWAY
        and name.vehicle_system == trailer_vehicle_system
    ):
        detail = f"industry group {name.industry_group}, vehicle system {name.vehicle_system}"
        return TRAILER, severity(TRAILER, untrained), "NAME", detail  # DET-18(a), DC-18
    category = NOT_IN_BASELINE if since_first_frame_s <= wake_window_s else UNRECOGNIZED
    detail = f"{what} {_since(since_first_frame_s)} after the session's first frame"
    return category, severity(category, untrained), "wake timing", detail


def reclassify(
    category: str,
    *,
    requested: Iterable[int] = (),
    sent: Iterable[int] = (),
    control_pgns: Iterable[int] = (),
    claimed_known_address: bool = False,
    ended_before_session: bool = False,
) -> Optional[tuple[str, str]]:
    """(classification_rule, reason) when the device stops fitting its category, else None."""
    if category not in (NOT_IN_BASELINE, TRAILER):
        return None
    requested, sent, control = set(requested), set(sent), set(control_pgns)
    diagnostic = sorted(requested - {PGN_CLAIM})
    if diagnostic:
        return "request activity", f"sent a diagnostic request (PGN {diagnostic[0]})"
    flagged = sorted((sent | requested) & control)
    if flagged:
        return "request activity", f"sent control PGN {flagged[0]}"
    memory = sorted(sent & MEMORY_PGNS)
    if memory:
        return "request activity", f"sent memory access PGN {memory[0]}"
    if category == TRAILER and claimed_known_address:
        return "NAME", "claimed an address held by a known ECU"
    if category == NOT_IN_BASELINE and ended_before_session:
        return "wake timing", "stopped sending before the session ended"
    return None


def reply_text(pgn: int, value: Optional[bytes]) -> Optional[str]:
    """The reply as text without its trailing ``*`` (Software ID without its count byte)."""
    if value is None:
        return None
    raw = value[1:] if pgn == PGN_SOFTWARE_ID and value else value
    text = raw.decode("ascii", "replace").rstrip("\x00\xff\ufffd ").rstrip("*")
    return text


def _self_reported(outcomes: Sequence[Any]) -> tuple[Optional[str], Optional[str]]:
    """Make and model from Component ID (fields 1 and 2) and ECU ID (field 5), IDN-3."""
    make = model = None
    for o in outcomes:
        if o.outcome != "reply":
            continue
        fields = [f.strip() for f in (reply_text(o.pgn, o.value) or "").split("*")]
        if o.pgn == PGN_COMPONENT_ID:
            make = make or (fields[0] if fields and fields[0] else None)
            model = model or (fields[1] if len(fields) > 1 and fields[1] else None)
        elif o.pgn == PGN_ECU_ID and len(fields) > 4 and fields[4]:
            make = make or fields[4]
    return make, model


@dataclass(frozen=True)
class _Score:
    entry: Mapping[str, Any]
    score: float
    gated: bool  # the entry's functions list was non-empty and passed


def _scores(
    name: Optional[Name], requested: set[int], sent: set[int], library: Optional[Library]
) -> list[_Score]:
    out = []
    for e in library.devices if library is not None else ():
        functions = list(e.get("functions") or [])
        if functions and (name is None or name.function not in functions):
            continue  # function-code gate (IDN-4)
        typical = set(e.get("requests_typical") or [])
        union = requested | typical
        jaccard = len(requested & typical) / len(union) if union else 0.0
        never = set(e.get("requests_never") or ()) & requested
        never |= set(e.get("sends_never") or ()) & sent
        out.append(_Score(e, max(0.0, jaccard - 0.25 * len(never)), bool(functions)))
    return out


def _broader(types: Sequence[str]) -> str:
    heads = {t.split(",", 1)[0].strip() for t in types}
    return heads.pop() if len(heads) == 1 and all("," in t for t in types) else "external device"


def _norm(v: Optional[str]) -> Optional[str]:
    return v.strip().casefold() if v else None


@dataclass(frozen=True)
class Identification:
    category: str
    sev: str  # the connection's severity
    classification_rule: str
    type_guess: Optional[str]
    make: str
    model: Optional[str]
    make_source: str
    confidence: str
    id_source: list[str]
    profile_match: Optional[str] = None
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    candidates: Optional[list[str]] = None
    reclassified: Optional[str] = None

    def changed_from(self, other: Identification) -> bool:
        """True when the type, make or model differ (IDN-4: then final_identification)."""
        mine = (self.type_guess, self.make, self.model)
        return mine != (other.type_guess, other.make, other.model)


def identify(
    conn: Connection,
    outcomes: Sequence[Any],
    requested: Iterable[int],
    library: Optional[Library],
    *,
    tie_margin: float,
    sent: Iterable[int] = (),
    classification_rule: str = "wake timing",
    reclassified: Optional[tuple[str, str]] = None,
    untrained: bool = False,
) -> Identification:
    """Identify one connection from its NAME, identity replies and requests (IDN-3, IDN-4)."""
    name = conn.name
    requested, sent = set(requested), set(sent)
    category, rule = conn.category, classification_rule
    reason = None
    if reclassified is not None:
        category, (rule, reason) = UNRECOGNIZED, reclassified
    sources: list[str] = []
    reductions = 0

    # -- library score (IDN-4) ------------------------------------------------
    scored = [s for s in _scores(name, requested, sent, library) if s.score > 0]
    type_guess: Optional[str] = None
    candidates: Optional[list[str]] = None
    lib_make = lib_model = None
    top: list[_Score] = []
    if scored:
        best = max(s.score for s in scored)
        top = [s for s in scored if s.score >= best - tie_margin]
        exact = [s for s in top if s.score == best]
        if len(top) > 1 and len(exact) == len(top):
            hinted = [s for s in top if conn.sa in (s.entry.get("sa_hints") or ())]
            if len(hinted) == 1:
                top = hinted  # an SA hint breaks an exact tie only
        types = sorted({str(s.entry["type"]) for s in top})
        makes = {s.entry.get("make") for s in top}
        if len(types) == 1:
            type_guess = types[0]
            if len(makes) == 1:  # one make (or all generic) among the near-ties
                lib_make, lib_model = top[0].entry.get("make"), top[0].entry.get("model")
        else:
            type_guess, candidates = _broader(types), types
            reductions += 1  # IDN-4: a type tie lowers the confidence
        sources.append("request pattern")
    name_counts = rule == "NAME" or any(s.gated for s in top)

    # -- make and model (IDN-3) -----------------------------------------------
    self_make, self_model = _self_reported(outcomes)
    code = str(name.mfr_code) if name is not None else None
    list_make = (library.manufacturers.get(code) if library is not None and code else None) or None
    make: Optional[str] = None
    make_source = "none"
    for value, src in ((self_make, "self-reported"), (list_make, "manufacturer code"),
                       (lib_make, "library")):  # fmt: skip
        if value:
            make, make_source = value, src
            break
    model = self_model or lib_model
    profile = None
    if (make_source == "library") or (model and not self_model and lib_model):
        profile = f"matches {' '.join(str(v) for v in (lib_make, lib_model) if v)} profile"
        reductions += 1  # IDN-3: a make or model only from the library
    if self_make or self_model:
        sources.insert(0, "self-reported reply")
    if list_make:
        name_counts = True
    if name_counts:
        sources.insert(0, "NAME")
    if make is None:
        if name is None:
            make = "unknown (no NAME)"
        elif library is not None and library.manufacturers:
            make = f"unknown (mfr code {name.mfr_code} not in the list)"
        else:
            make = f"unknown (mfr code {name.mfr_code}; no manufacturer list loaded)"

    # -- disagreements (IDN-3) ------------------------------------------------
    offered = [
        ("self-reported", self_make, self_model),
        ("manufacturer code", list_make, None),
        ("library", lib_make, lib_model),
    ]
    offered = [o for o in offered if o[1] or o[2]]
    makes_seen = {_norm(m) for _, m, _ in offered if m}
    models_seen = {_norm(m) for _, _, m in offered if m}
    disagreements = []
    if len(makes_seen) > 1 or len(models_seen) > 1:
        disagreements = [{"source": s, "make": m, "model": mo} for s, m, mo in offered]

    level = max(0, min(len(sources), 3) - 1 - reductions)
    return Identification(
        category=category,
        sev=severity(category, untrained),
        classification_rule=rule,
        type_guess=type_guess,
        make=make,
        model=model,
        make_source=make_source,
        confidence=CONFIDENCE[level],
        id_source=sources,
        profile_match=profile,
        disagreements=disagreements,
        candidates=candidates,
        reclassified=reason,
    )


def identification_fields(
    ident: Identification,
    outcomes: Sequence[Any],
    to_utc: Callable[[float], Optional[datetime]],
) -> dict[str, Any]:
    """The identification fields after ``sa``, in the example's order (DC-17)."""
    requests = []
    for o in outcomes:
        item: dict[str, Any] = {
            "pgn": o.pgn,
            "name": REQUEST_NAMES.get(o.pgn),
            "sent": format_utc(to_utc(o.sent_mono)),
            "outcome": o.outcome,
        }
        if o.outcome == "reply":
            item["value"] = reply_text(o.pgn, o.value)
        requests.append(item)
    return {
        "requests": requests,
        "make": ident.make,
        "model": ident.model,
        "make_source": ident.make_source,
        "type_guess": ident.type_guess,
        "confidence": ident.confidence,
        "id_source": list(ident.id_source),
        "profile_match": ident.profile_match,
        "disagreements": list(ident.disagreements),
        "candidates": ident.candidates,
        "category": ident.category,
        "classification_rule": ident.classification_rule,
        "reclassified": ident.reclassified,
    }


def identification_record(
    conn: Connection,
    ident: Identification,
    outcomes: Sequence[Any],
    to_utc: Callable[[float], Optional[datetime]],
) -> Record:
    """The ``identification`` record (notice, log-format); time set by the caller."""
    fields = {"sa": conn.sa, **identification_fields(ident, outcomes, to_utc)}
    return Record("identification", "notice", None, None, fields, conn.conn)
