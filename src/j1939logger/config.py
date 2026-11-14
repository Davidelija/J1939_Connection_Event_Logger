"""config: validate and version the config; validate inventory and library files.

docs/modules.md section 4, contract v1, frozen for step 2. Layer 2: pure (no
I/O, no clock); ``store`` loads the bytes, this module checks them.

* ``validate(new, old) -> Config | ConfigError`` (STS-9, LOG-13, LOG-19):
  exactly the keys in the requirements' Configuration table plus the version
  header (``format``, ``config``, ``created_utc``, ``operator``, ``change``);
  unknown or missing keys and wrong types are rejected and listed; additions to
  ``requests.allow_list`` or ``transmit.allow_list`` beyond this release's
  lists (or the previous config's) are rejected; ``detection.move_grace_s``
  over 5 s is rejected. A change from ``old`` that weakens detection is
  reported in ``Config.weakens`` (it needs ``--confirm``, STS-9 c).
* ``validate_inventory(data) -> Inventory | InventoryError`` (``inv-1``).
* ``validate_library(data) -> Library | LibraryError`` (``lib-1``).
* ``change_record`` and ``rejected_record`` build the ``config_change`` and
  ``config_rejected`` records for a push (used from step 7).

Unknown format versions are refused (LOG-19).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Callable, Optional, Union

from j1939logger.transmit import RELEASE_REQUEST_ALLOW, RELEASE_TRANSMIT_ALLOW
from j1939logger.types import CATEGORIES, Record

__all__ = [
    "Config",
    "ConfigError",
    "Inventory",
    "InventoryEntry",
    "InventoryError",
    "Library",
    "LibraryError",
    "validate",
    "validate_inventory",
    "validate_library",
    "change_record",
    "rejected_record",
    "parse_json",
    "RELEASE_TRANSMIT_ALLOW",
    "RELEASE_REQUEST_ALLOW",
]

# The allow-lists this release may use are defined once, in transmit (NP-9).
MAX_MOVE_GRACE_S = 5.0

_HEX_NAME = re.compile(r"^0x[0-9A-Fa-f]{16}$")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return (isinstance(v, (int, float))) and not isinstance(v, bool)


def _int_list(v: Any) -> bool:
    return isinstance(v, list) and all(_is_int(x) for x in v)


def _str(v: Any) -> bool:
    return isinstance(v, str)


def _name(v: Any) -> bool:
    return isinstance(v, str) and bool(_HEX_NAME.match(v))


def _str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


# Every key in the requirements' Configuration table, with its type check.
SCHEMA: dict[str, Callable[[Any], bool]] = {
    "can.interface": _str,
    "can.termination": lambda v: v in ("off", "on"),
    "can.bitrates": lambda v: _int_list(v) and set(v) <= {250000, 500000} and bool(v),
    "can.bitrate_check_frames": _is_int,
    "can.bitrate_fault_s": _is_num,
    "can.rx_buffer_bytes": _is_int,
    "network.address": _str,
    "address.name": _name,
    "address.claim_from": _is_int,
    "address.claim_down_to": _is_int,
    "address.reserved": _int_list,
    "address.claim_wait_ms": _is_num,
    "address.claim_retries": _is_int,
    "requests.allow_list": _int_list,
    "requests.vin_sa": _is_int,
    "requests.sweep_interval_min": _is_num,
    "requests.timeout_s": _is_num,
    "requests.retries": _is_int,
    "transmit.allow_list": _int_list,
    "transmit.max_frames_per_s": _is_num,
    "transmit.max_outstanding_per_dest": _is_int,
    "detection.silence_end_s": _is_num,
    "detection.requests_kept": _is_int,
    "detection.control_pgns": _int_list,
    "detection.known_device_new_pgn": lambda v: isinstance(v, bool),
    "detection.move_grace_s": _is_num,
    "detection.first_sweep_wait_s": _is_num,
    "classify.wake_window_s": _is_num,
    "classify.trailer_vehicle_system": _is_int,
    "identify.tie_margin": _is_num,
    "limits.tp_sessions": lambda v: _is_int(v) and v >= 1,
    "limits.pgns_per_conn": _is_int,
    "limits.raw_mb_per_session": _is_num,
    "session.end_silence_s": _is_num,
    "logging.session_rollover_h": _is_num,
    "logging.sync_interval_s": _is_num,
    "logging.hash": lambda v: v == "sha256",
    "logging.raw_before_s": _is_num,
    "logging.raw_after_s": _is_num,
    "storage.event_reserve_mb": _is_num,
    "storage.warn_pct": _is_num,
    "diag.max_bytes": _is_int,
    "diag.files": lambda v: _is_int(v) and v >= 1,
    "watchdog.timeout_s": _is_num,
    "restart_guard.count": _is_int,
    "restart_guard.window_min": _is_num,
    "clock.max_skew_min": _is_num,
    "training.timeout_min": _is_num,
    "training.states": _str_list,
    "install.connector": _str,
    "install.network": _str,
}
HEADER: dict[str, Callable[[Any], bool]] = {
    "format": lambda v: v == "cfg-1",
    "config": lambda v: isinstance(v, str) and bool(re.match(r"^cfg-v\d+$", v)),
    "created_utc": _str,
    "operator": _str,
    "change": _str,
}


class ConfigError(Exception):
    """A config that fails validation; ``reasons`` lists each problem."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class InventoryError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class LibraryError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Config:
    """A validated config: read-only, looked up by dotted key (``cfg["limits.tp_sessions"]``)."""

    version: str
    values: Mapping[str, Any]
    header: Mapping[str, Any]
    changed: tuple[str, ...] = ()
    weakens: tuple[str, ...] = ()

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    @property
    def number(self) -> int:
        return int(self.version.split("-v")[1])


def parse_json(data: Union[bytes, str]) -> Any:
    """Parse JSON from a file's bytes; a bad file raises ValueError."""
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc


def _flatten(data: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    values: dict[str, Any] = {}
    header: dict[str, Any] = {}
    unknown: list[str] = []
    for key, value in data.items():
        if key in HEADER:
            header[key] = value
        elif isinstance(value, dict):
            for sub, v in value.items():
                dotted = f"{key}.{sub}"
                if dotted in SCHEMA:
                    values[dotted] = v
                else:
                    unknown.append(dotted)
        else:
            unknown.append(key)
    return values, header, unknown


def _weakens(new: Mapping[str, Any], old: Mapping[str, Any]) -> list[str]:
    out = []
    if set(old["detection.control_pgns"]) - set(new["detection.control_pgns"]):
        out.append("detection.control_pgns (control PGN removed)")
    if old["detection.known_device_new_pgn"] and not new["detection.known_device_new_pgn"]:
        out.append("detection.known_device_new_pgn (switch turned off)")
    for key in ("logging.raw_before_s", "logging.raw_after_s"):
        if new[key] < old[key]:
            out.append(f"{key} (shorter raw capture window)")
    if new["detection.silence_end_s"] > old["detection.silence_end_s"]:
        out.append("detection.silence_end_s (longer silence time)")
    if new["detection.move_grace_s"] > old["detection.move_grace_s"]:
        out.append("detection.move_grace_s (longer move grace)")
    return out


def validate(new: Mapping[str, Any], old: Optional[Config] = None) -> Union[Config, ConfigError]:
    """Validate a config (parsed JSON) against the schema and the previous version."""
    if not isinstance(new, Mapping):
        return ConfigError(["config is not a JSON object"])
    if new.get("format") not in (None, "cfg-1"):
        return ConfigError([f"unknown config format {new.get('format')!r}"])
    values, header, unknown = _flatten(new)
    reasons = [f"unknown key {k}" for k in sorted(unknown)]
    reasons += [f"missing key {k}" for k in sorted(set(HEADER) - set(header))]
    reasons += [f"missing key {k}" for k in sorted(set(SCHEMA) - set(values))]
    reasons += [
        f"bad value for {k}" for k, ok in HEADER.items() if k in header and not ok(header[k])
    ]
    reasons += [
        f"bad value for {k}" for k, ok in SCHEMA.items() if k in values and not ok(values[k])
    ]
    if reasons:
        return ConfigError(reasons)
    for key, release in (
        ("transmit.allow_list", RELEASE_TRANSMIT_ALLOW),
        ("requests.allow_list", RELEASE_REQUEST_ALLOW),
    ):
        allowed = set(release) & (set(old[key]) if old is not None else set(release))
        added = sorted(set(values[key]) - allowed)
        if added:
            reasons.append(
                f"{key} adds {added}; the allow-list changes only with a software release"
            )
    if values["detection.move_grace_s"] > MAX_MOVE_GRACE_S:
        reasons.append(f"detection.move_grace_s over {MAX_MOVE_GRACE_S:g} s")
    if reasons:
        return ConfigError(reasons)
    changed: tuple[str, ...] = ()
    weakens: tuple[str, ...] = ()
    if old is not None:
        changed = tuple(sorted(k for k in SCHEMA if values[k] != old[k]))
        weakens = tuple(_weakens(values, old.values))
    return Config(
        version=header["config"],
        values=MappingProxyType(values),
        header=MappingProxyType(header),
        changed=changed,
        weakens=weakens,
    )


def change_record(cfg: Config, old: Config, operator: str, utc: Optional[datetime]) -> Record:
    """``config_change`` for an accepted push: high if it weakens detection (STS-9)."""
    return Record(
        type="config_change",
        sev="high" if cfg.weakens else "notice",
        utc=utc,
        veh_time=None,
        fields={
            "operator": operator,
            "old_version": old.version,
            "new_version": cfg.version,
            "changed": list(cfg.changed),
            "weakens_detection": bool(cfg.weakens),
            "weakening": list(cfg.weakens),
        },
    )


def rejected_record(
    error: ConfigError, proposed: Optional[str], operator: str, utc: Optional[datetime]
) -> Record:
    """``config_rejected`` for a push that fails validation (STS-9 d)."""
    return Record(
        type="config_rejected",
        sev="notice",
        utc=utc,
        veh_time=None,
        fields={"operator": operator, "proposed_version": proposed, "reasons": list(error.reasons)},
    )


# -- inventory (inv-1) ---------------------------------------------------------


@dataclass(frozen=True)
class InventoryEntry:
    entry: str
    name: Optional[int]  # None for a device that never claims
    category: str
    addresses: tuple[int, ...]
    pgns_sent: tuple[int, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Inventory:
    version: str
    vin: str
    entries: tuple[InventoryEntry, ...]

    def by_name(self) -> dict[int, InventoryEntry]:
        return {e.name: e for e in self.entries if e.name is not None}


def validate_inventory(data: Any) -> Union[Inventory, InventoryError]:
    """Check an inventory file (``inv-1``); a corrupt one runs the logger untrained (STS-19)."""
    if not isinstance(data, Mapping):
        return InventoryError(["inventory is not a JSON object"])
    if data.get("format") != "inv-1":
        return InventoryError([f"unknown inventory format {data.get('format')!r}"])
    reasons = []
    for key in ("inventory", "vin", "entries"):
        if key not in data:
            reasons.append(f"missing key {key}")
    if reasons:
        return InventoryError(reasons)
    if not re.match(r"^inv-v\d+$", str(data["inventory"])):
        reasons.append("bad value for inventory")
    entries = []
    seen: set[str] = set()
    for i, e in enumerate(data["entries"] if isinstance(data["entries"], list) else []):
        where = f"entries[{i}]"
        if not isinstance(e, Mapping) or not isinstance(e.get("entry"), str):
            reasons.append(f"{where}: missing entry ID")
            continue
        if e["entry"] in seen:
            reasons.append(f"{where}: duplicate entry ID {e['entry']}")
        seen.add(e["entry"])
        name = e.get("name")
        if name is not None and not _name(name):
            reasons.append(f"{where}: bad NAME")
            continue
        if e.get("category") not in CATEGORIES:
            reasons.append(f"{where}: bad category {e.get('category')!r}")
            continue
        addresses = e.get("addresses", [])
        if not _int_list(addresses) or (name is None and not addresses):
            reasons.append(f"{where}: bad addresses")
            continue
        pgns = e.get("pgns_sent", [])
        if not _int_list(pgns):
            reasons.append(f"{where}: bad pgns_sent")
            continue
        entries.append(
            InventoryEntry(
                entry=e["entry"],
                name=int(name, 16) if name else None,
                category=e["category"],
                addresses=tuple(addresses),
                pgns_sent=tuple(pgns),
                raw=MappingProxyType(dict(e)),
            )
        )
    if not isinstance(data["entries"], list):
        reasons.append("entries is not a list")
    if reasons:
        return InventoryError(reasons)
    return Inventory(version=str(data["inventory"]), vin=str(data["vin"]), entries=tuple(entries))


# -- device library (lib-1) ------------------------------------------------------


@dataclass(frozen=True)
class Library:
    version: str
    devices: tuple[Mapping[str, Any], ...]
    manufacturers: Mapping[str, str]  # the manufacturer code list (IDN-2), shipped empty


_DEVICE_LISTS: tuple[str, ...] = (
    "functions",
    "sa_hints",
    "requests_typical",
    "sends_typical",
    "requests_never",
    "sends_never",
)


def validate_library(data: Any) -> Union[Library, LibraryError]:
    """Check a device library file (``lib-1``), including its manufacturer list (IDN-2, IDN-5)."""
    if not isinstance(data, Mapping):
        return LibraryError(["library is not a JSON object"])
    if data.get("format") != "lib-1":
        return LibraryError([f"unknown library format {data.get('format')!r}"])
    reasons = []
    if not re.match(r"^lib-v\d+$", str(data.get("library", ""))):
        reasons.append("bad value for library")
    devices = data.get("devices")
    if not isinstance(devices, list):
        reasons.append("devices is not a list")
        devices = []
    for i, d in enumerate(devices):
        if not isinstance(d, Mapping) or not isinstance(d.get("type"), str):
            reasons.append(f"devices[{i}]: missing type")
            continue
        for key in _DEVICE_LISTS:
            if not _int_list(d.get(key, [])):
                reasons.append(f"devices[{i}]: bad {key}")
    mfr = data.get("manufacturers")
    codes = mfr.get("codes") if isinstance(mfr, Mapping) else None
    if not isinstance(codes, Mapping) or not all(
        str(k).isdigit() and isinstance(v, str) for k, v in codes.items()
    ):
        reasons.append("bad manufacturers.codes")
        codes = {}
    if reasons:
        return LibraryError(reasons)
    return Library(
        version=str(data["library"]),
        devices=tuple(MappingProxyType(dict(d)) for d in devices),
        manufacturers=MappingProxyType({str(k): str(v) for k, v in codes.items()}),
    )
