"""Shared types (docs/modules.md section 1, contract v1).

Defined once and imported everywhere; tests build fixtures from these.
Field names are the contract.

Python 3.9 floor (DC-1): this module starts with ``from __future__ import
annotations``. Optional fields are written ``Optional[X]`` rather than
``X | None`` because these annotations are evaluated at run time by
``typing.get_type_hints`` (for example by Hypothesis ``st.builds`` and
``st.from_type``), which fails on Python 3.9 for ``X | None``.

The enumerations from the requirements' Enumerated values table are string
constants with the requirements' spellings (docs/modules.md section 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

__all__ = [
    "Frame",
    "J1939Msg",
    "Name",
    "ClockReading",
    "Record",
    "Connection",
    "PlatformError",
    "SEVERITIES",
    "CATEGORIES",
    "END_REASONS",
    "LOGGER_STATES",
    "REQUEST_OUTCOMES",
    "ID_SOURCES",
    "CONFIDENCES",
    "CLOCK_SOURCES",
    "MAKE_SOURCES",
    "CLASSIFICATION_RULES",
    "VIN_STATUSES",
    "PREV_SESSION_ENDS",
    "RESET_MODES",
    "APPROVAL_KINDS",
    "REMOVAL_KINDS",
    "ROLES",
]


@dataclass(frozen=True)
class Frame:
    """One raw CAN frame from capture."""

    ts_kernel: float  # kernel receive time, seconds (SO_TIMESTAMP, wall clock at receipt)
    ts_mono: float  # ts_kernel converted to monotonic time: ts_kernel - (wall - mono), sampled
    # at read time; not the time the batch was read (valid because the clock is never stepped, X27)
    can_id: int  # 29-bit or 11-bit identifier
    extended: bool  # True for 29-bit
    remote: bool
    error: bool  # error frame (flags in data)
    data: bytes  # 0 to 8 bytes
    own: bool  # sent by this logger (loopback)


@dataclass(frozen=True)
class J1939Msg:
    """One J1939 message after decode (single frame or reassembled transfer)."""

    ts_mono: float  # time of the first frame (for transfers: the RTS or BAM)
    ts_kernel: float
    priority: int
    pgn: int
    sa: int
    da: int  # 255 for broadcast
    data: bytes  # full payload, up to 1785 bytes
    via_tp: bool
    own: bool  # sent by this logger
    reply_to_logger: bool  # addressed to the logger's own address


@dataclass(frozen=True)
class Name:
    """The 64-bit NAME and its decoded fields (raw numbers, IDN-1)."""

    value: int
    aac: int
    industry_group: int
    vs_instance: int
    vehicle_system: int
    function: int
    function_instance: int
    ecu_instance: int
    mfr_code: int
    identity: int


@dataclass(frozen=True)
class ClockReading:
    wall_utc: Optional[datetime]  # None when no valid source
    mono: float
    source: str  # "rtc" | "vehicle" | "elapsed" (requirements enum)
    valid: bool


@dataclass
class Record:
    """A log record before eventlog adds written, prev and hash.

    eventlog adds rec, written, prev and hash, and assigns event_id. Every utc
    comes from clock.to_utc(ts_mono), never from Frame.ts_kernel directly (X27).
    """

    type: str  # record type from docs/log-format.md
    sev: str  # "info" | "notice" | "high"
    utc: Optional[datetime]  # event time
    veh_time: Optional[datetime]
    fields: dict  # the type-specific fields, exactly as in docs/log-format.md
    conn: Optional[int] = None
    event_id: Optional[str] = None  # "<session>-<n>", assigned by eventlog for events


@dataclass
class Connection:
    """One external device's connection, owned by detect."""

    conn: int
    key: tuple  # ("name", value) or ("sa", address) for a device that never claims
    sa: int
    name: Optional[Name]
    start_mono: float
    last_mono: float
    category: str  # Category enum in the requirements


class PlatformError(Exception):
    """The only exception type platform raises."""

    kind: str  # a value from the Kind column of docs/errors.md (the single list of fault kinds)

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind


# Enumerated values (docs/requirements.md, Enumerated values), exact spellings.
# Where the requirements table adds a note in parentheses that names a config
# key or a synonym, the note is not part of the value (see the step 1 pull
# request): "silence (detection.silence_end_s)" -> "silence",
# "needs training (untrained)" -> "needs training", "NAME (analysis only)" -> "NAME".

SEVERITIES = ("info", "notice", "high")

CATEGORIES = (
    "vehicle ECU in baseline",
    "vehicle ECU not in baseline",
    "trailer device",
    "external device (approved)",
    "external device (unrecognized)",
)

END_REASONS = (
    "silence",
    "key-off",
    "power loss",
    "software restart",
    "watchdog restart",
    "session roll-over",
)

LOGGER_STATES = (
    "starting",
    "detecting bit rate",
    "recording",
    "training",
    "needs training",
    "fault",
)

REQUEST_OUTCOMES = ("reply", "NACK", "no reply")

ID_SOURCES = ("NAME", "self-reported reply", "request pattern")

CONFIDENCES = ("high", "medium", "low")

CLOCK_SOURCES = ("rtc", "vehicle", "elapsed")

MAKE_SOURCES = ("self-reported", "manufacturer code", "library", "none")

CLASSIFICATION_RULES = ("in inventory", "wake timing", "request activity", "NAME")

VIN_STATUSES = ("match", "mismatch", "unavailable")

PREV_SESSION_ENDS = (
    "clean",
    "power loss",
    "software restart",
    "watchdog restart",
    "software update",
)

RESET_MODES = ("restart", "retrain", "move", "wipe")

APPROVAL_KINDS = ("device", "PGN sent", "PGN requested", "address")

REMOVAL_KINDS = ("remove device", "remove PGN sent", "remove PGN requested")

ROLES = ("operator", "admin")
