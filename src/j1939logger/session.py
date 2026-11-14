"""session: the session lifecycle and the main loop (docs/modules.md section 4, contract v1).

Layer 4; frozen for step 2, with the step 3 rules of DC-12.

Lifecycle:

* ``start()`` (power-on) opens capture listen-only and opens a session.
* Bit rate (NP-1, NP-2, NP-17): listen-only until ``platform.bitrate_check()``
  confirms 250000 or 500000, tried on every loop; after ``can.bitrate_fault_s``
  without one, a high fault (once). Once confirmed, capture switches to normal
  mode and, unless the restart guard holds, ``transmit`` is enabled, the
  logger claims an address (``address``) and the request schedule starts
  (``requests``).
* The ``session_start`` header is written once the claim has settled
  (``address.claim_wait_ms`` after it was sent), so it carries the claim
  result; records produced before then are written right after it. Without a
  confirmed bit rate the header is written at once.
* Each ``step()`` kicks the watchdog (STS-18), reads frames, and runs
  ``decode`` -> ``address`` -> ``requests`` -> ``clock`` -> ``detect`` ->
  ``eventlog``; a ``connection_start`` is synced at once (DET-16) and its
  device is asked for its identity (NP-13). ``transmit`` sends what the
  limits allow.
* Bus-off or TX error-passive (``decode.bus_state``) turns transmit off for
  the session (NP-3).
* Restart guard (NP-19, DC-12): ``state.json`` keeps ``unclean_starts``; when
  ``restart_guard.count`` fall within ``restart_guard.window_min`` the session
  starts listen-only with transmit off and a high fault "restart loop;
  transmit disabled". A clean session end clears the list.
* VIN (NP-12, DC-12): the header has ``vin_status`` "pending"; a ``vin_check``
  record follows the VIN reply, NACK or no reply.
* Key-off after ``session.end_silence_s``; a new session on the next frame;
  roll-over after ``logging.session_rollover_h`` (LOG-2, LOG-17, DC-10, DC-11).
  ``transmit``, ``address`` and ``requests`` are new for each session.

Numbering and the chain (LOG-5, DC-10): the next session number is one more
than the higher of ``state.json`` and the newest session file; the first
``prev`` is the last complete hash of the newest file, or 64 zeros (a new card
when a state file exists). Previous end: clean, the diagnostic log's restart
cause, or power loss with ``bytes_cut_off``.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.address import Address
from j1939logger.admin import RESTART_EXIT, DiagLog, reset_record
from j1939logger.capture import Capture
from j1939logger.clock import Clock
from j1939logger.config import (
    Config,
    ConfigError,
    Inventory,
    Library,
    LibraryError,
    change_record,
    rejected_record,
    validate,
    validate_inventory,
    validate_library,
)
from j1939logger.decode import bus_state, decode, new_state
from j1939logger.detect import Detect
from j1939logger.eventlog import ZERO_HASH, EventLog, format_utc, scan_tail
from j1939logger.identify import (
    Identification,
    classify,
    identification_fields,
    identification_record,
    identify,
    reclassify,
)
from j1939logger.inventory import (
    InventoryRefused,
    Training,
    approve,
    confirm_record,
    next_version,
    rejection_record,
    remove,
)
from j1939logger.monitor import Monitor
from j1939logger.platform.interface import Platform
from j1939logger.rawcap import RawCap
from j1939logger.requests import PGN_VIN, RequestOutcome, Requests
from j1939logger.retention import RawFile, Retention
from j1939logger.status import State, Status
from j1939logger.store import Store
from j1939logger.transmit import Transmit
from j1939logger.types import Connection, Frame, J1939Msg, Name, PlatformError, Record, TxRequest

__all__ = ["Session", "settings_from_config", "SessionFile", "session_files", "SW_VERSION"]

SW_VERSION = "0.0.0"
LOG_FORMAT = "log-1"
STATE_FORMAT = "state-1"
BITRATES = (250000, 500000)

# The config keys step 1 read directly (DC-9); kept for callers passing a nested cfg-1.
STEP1_KEYS = (
    ("can", "rx_buffer_bytes"),
    ("logging", "raw_before_s"),
    ("limits", "tp_sessions"),
    ("clock", "max_skew_min"),
    ("classify", "wake_window_s"),
)

_NAME = re.compile(r"^s(\d{6})_([0-9TZ]+|noclock)(?:_p(\d+))?\.jsonl$")


def settings_from_config(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Every ``section.key`` -> value from a nested cfg-1 config."""
    out: dict[str, Any] = {}
    for section, value in cfg.items():
        if isinstance(value, Mapping):
            for key, v in value.items():
                out[f"{section}.{key}"] = v
    for section, key in STEP1_KEYS:
        if f"{section}.{key}" not in out:
            raise ValueError(f"config is missing {section}.{key}")
    return out


@dataclass(frozen=True)
class SessionFile:
    path: Path
    session: int
    stamp: str
    part: int


def session_files(folder: Path) -> list[SessionFile]:
    """Session files in a folder, oldest first (by session number, then part)."""
    if not folder.is_dir():
        return []
    out = []
    for p in folder.iterdir():
        m = _NAME.match(p.name)
        if m:
            out.append(SessionFile(p, int(m.group(1)), m.group(2), int(m.group(3) or 1)))
    return sorted(out, key=lambda f: (f.session, f.part))


def _vin_text(value: Optional[bytes]) -> Optional[str]:
    if not value:
        return None
    text = value.split(b"*", 1)[0].decode("ascii", "replace").strip()
    return text or None


# session_end reason -> Connection end reason for the connections still open (DET-6).
CONNECTION_END_REASON = {
    "key-off, bus silent": "key-off",
    "service stopped": "software restart",
}


def _refused(error: str, next_step: str) -> dict[str, Any]:
    return {"proto": 1, "ok": False, "error": error, "next": next_step}


def card_files(card: Path) -> list[dict[str, Any]]:
    """Session files, raw captures and diagnostic files on the card, with size and SHA-256.

    ``j1939cmd`` answers ``retrieve_list`` with this even when the service is down (DC-21).
    """
    out = []
    for sub in ("sessions", "raw", "diag"):
        folder = card / sub
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if not p.is_file():
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            out.append({"path": f"{sub}/{p.name}", "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})  # fmt: skip
    return out


def _version_number(version: str) -> Optional[int]:
    m = re.match(r"^inv-v(\d+)$", version)
    return int(m.group(1)) if m else None


@dataclass
class _Ident:
    """What session keeps per connection for identify (step 5, DC-17)."""

    conn: Connection
    rule: str  # classification_rule at connection start
    outcomes: list[RequestOutcome] = field(default_factory=list)
    ident: Optional[Identification] = None


APPROVED = "external device (approved)"
IDENTITY_REQUESTS = 3  # Component ID, Software ID, ECU ID (NP-13)


class Session:
    def __init__(
        self,
        platform: Platform,
        settings: Mapping[str, Any],
        inventory: Optional[Inventory],
        versions: Optional[Mapping[str, Optional[str]]] = None,
        startup_faults: Optional[list[str]] = None,
    ) -> None:
        self._platform = platform
        self._settings = settings
        self._inventory = inventory  # config.Inventory, or None when untrained (DC-13)
        entries = inventory.entries if inventory is not None else ()
        self._inventory_addresses = tuple(a for e in entries for a in e.addresses)
        self._inventory_vin = inventory.vin if inventory is not None else None
        self._versions = dict(versions or {})
        self._startup_faults = list(startup_faults or [])
        name = settings.get("address.name", "0x9FFEFFFFFFE00001")
        self._logger_name = int(name, 16) if isinstance(name, str) else int(name)
        self.clock = Clock(platform, float(settings["clock.max_skew_min"]))
        self.store = Store(platform)
        self.diag = DiagLog(
            platform,
            self.clock,
            int(settings.get("diag.max_bytes", 10 * 1024 * 1024)),
            int(settings.get("diag.files", 5)),
        )
        self.capture = Capture(
            platform,
            rx_buffer_bytes=int(settings["can.rx_buffer_bytes"]),
            raw_before_s=float(settings["logging.raw_before_s"]),
        )
        self._sessions_dir = platform.paths().card / "sessions"
        self._stop = threading.Event()
        self.eventlog: Optional[EventLog] = None
        self.detect: Optional[Detect] = None
        self.monitor: Optional[Monitor] = None
        self._no_sweep_sent = False
        self._connections_started = 0
        self.transmit: Optional[Transmit] = None
        self.address: Optional[Address] = None
        self.requests: Optional[Requests] = None
        self.outcomes: list[RequestOutcome] = []  # identity outcomes, for identify (step 5)
        self.library: Optional[Library] = None
        self._library_fault: Optional[str] = None
        self._idents: dict[int, _Ident] = {}
        self.rawcap: Optional[RawCap] = None
        self.retention: Optional[Retention] = None
        self.training: Optional[Training] = None
        self._proposal: Optional[dict[str, Any]] = None
        self._dropped = False  # inventory dropped for the session (VIN mismatch, training)
        self._vin_received: Optional[str] = None
        self.status = Status(platform, settings)
        self._unreviewed: list[str] = []  # high events not yet cleared (STS-2, DC-21)
        self._retrieved: list[str] = []  # files the laptop has retrieved (LOG-11)
        self._inventory_active = True  # False after retrain until a training is confirmed
        self._high_fault: Optional[str] = None
        self._vin_status: Optional[str] = None
        self._status_mono = float("-inf")
        self.exit_code = 0
        self._end_sets: dict[int, frozenset[int]] = {}
        baseline = inventory.entries if inventory is not None else ()
        self._known_addresses = {
            a
            for e in baseline
            if e.name is not None and e.category != APPROVED
            for a in e.addresses
        }
        self._first_open = True
        self._prev_hash = ZERO_HASH
        self._next_session = 1
        self._session = 0
        self._part = 1
        self._stamp = ""
        self._wake = "power-on"
        self._prev_info: dict[str, Any] = {}
        self._new_card = False
        self._counts: dict[str, int] = {}
        self._frames_rx = 0
        self._error_frames = 0
        self._last_frame_mono = 0.0
        self._part_start_mono = 0.0
        self._open_mono = 0.0
        self._decode_state = new_state(int(settings["limits.tp_sessions"]))
        self._decode_stats = self._decode_state.stats
        self._header_pending = False
        self._buffer: list[tuple[Record, Optional[float]]] = []
        self._claim_sent_mono: Optional[float] = None
        self._bitrate: Optional[int] = None
        self._bitrate_fault_logged = False
        self._guard_holds = False
        self._unclean_starts: list[Optional[str]] = []
        self._bus_off = False
        self._reset_counts()

    # -- settings ---------------------------------------------------------------

    def _get(self, key: str, default: Any) -> Any:
        return self._settings.get(key, default)

    # -- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        """Power-on: load the device library, open capture listen-only and the first session."""
        self._load_library()
        self.capture.start(listen_only=True)
        self._open_session(wake="power-on")

    def _load_library(self) -> None:
        """The newest device library on the card (IDN-5); a corrupt one is a high fault (DC-19)."""
        data = self.store.load("library")
        if data is None:
            return  # no library: identification without library matches
        try:
            checked = validate_library(json.loads(data.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            checked = LibraryError([f"not JSON: {exc}"])
        if isinstance(checked, LibraryError):
            self._library_fault = f"device library corrupt ({checked})"
            return
        self.library = checked
        self._versions["library"] = checked.version

    def stop(self) -> None:
        self._stop.set()

    def run(self, idle_s: float = 0.01) -> Optional[PlatformError]:
        """Loop until ``stop()``; returns the PlatformError that ended it, if any."""
        error: Optional[PlatformError] = None
        try:
            while not self._stop.is_set():
                if self.step() == 0:
                    self._stop.wait(idle_s)
        except PlatformError as exc:
            error = exc
            self.diag.log("error", "session", f"{exc.kind}: {exc}")
        finally:
            self.capture.stop()
            if self.eventlog is not None and self.exit_code == RESTART_EXIT and error is None:
                self._leave_for_restart()
            elif self.eventlog is not None:
                self._close_session(
                    "service stopped" if error is None else f"stopped: {error.kind}"
                )
            self.diag.flush()
        return error

    def _leave_for_restart(self) -> None:
        """Operator restart (STS-11): connections end with "software restart" and the file is
        left without session_end, so the next session records a software restart (LOG-18)."""
        assert self.eventlog is not None
        if self._header_pending:
            self._claim_sent_mono = None
            self._settle_header()
        self._collect()
        self._end_connections("software restart")
        if self.rawcap is not None:
            self.rawcap.close()
        self.eventlog.sync_now()
        self.eventlog.close()
        self._prev_hash = self.eventlog.last_hash
        self._write_state(self._session)
        self.diag.restart_cause("software restart")  # the last diagnostic entry
        self.eventlog = None

    @property
    def open(self) -> bool:
        return self.eventlog is not None

    @property
    def logger_sa(self) -> Optional[int]:
        return self.address.current if self.address is not None else None

    def step(self, max_n: int = 1000) -> int:
        """Process the frames already received and the session timers; returns frame count."""
        self._platform.watchdog_kick()
        frames = self.capture.read_batch(max_n)
        if frames and self.eventlog is None:
            self._open_session(wake="CAN activity")
        if self.eventlog is not None:
            self._try_bitrate()
        if frames:
            self._process(frames)
        if self.eventlog is not None:
            self._settle_header()
            self._run_requests()
            self._collect()
            self._detection()
            self._raw_poll()
            self._update_status()
        self._timers()
        self._drain_faults()
        return len(frames)

    # -- transmitting -------------------------------------------------------------

    def _try_bitrate(self) -> None:
        if self._bitrate is not None:
            return
        rate = self._platform.bitrate_check()
        if rate in BITRATES:
            self._bitrate = rate
            self.capture.set_mode(listen_only=False)  # NP-2
            if self._guard_holds:
                return  # NP-19: listen-only with transmit off
            assert self.transmit is not None and self.address is not None
            self.transmit.enable(self.capture.transmit_handle())
            self._submit(self.address.start())
            self._claim_sent_mono = self.clock.mono()
            assert self.requests is not None
            self.requests.session_start()
            self.transmit.pump()
            return
        waited = self.clock.mono() - self._open_mono
        if not self._bitrate_fault_logged and waited >= float(self._get("can.bitrate_fault_s", 60)):
            self._bitrate_fault_logged = True  # NP-17: keep trying, log once
            self._log(
                Record(
                    "fault",
                    "high",
                    None,
                    None,
                    {
                        "cause": f"no bit rate confirmed within {waited:.0f} s",
                        "logger_action": "listen-only; still trying",
                    },
                )
            )

    def _submit(self, sends: Iterable[tuple[TxRequest, int]]) -> None:
        if self.transmit is None:
            return
        for req, sa in sends:
            self.transmit.submit(req, sa)
        if self.address is not None:
            self.transmit.set_source(self.address.current)

    def _run_requests(self) -> None:
        if self.transmit is None or self.requests is None or not self.transmit.enabled:
            return
        if self.logger_sa is not None:
            for req in self.requests.poll():
                self.transmit.submit(req, self.logger_sa)
        self.transmit.pump()

    def _collect(self) -> None:
        """Records and outcomes from address, requests and transmit."""
        if self.requests is not None:
            for record in self.requests.take_records():
                self._log(record)
            for outcome in self.requests.take_outcomes():
                if outcome.pgn == PGN_VIN and outcome.conn is None:
                    check = self._vin_check(outcome)
                    self._log(check)
                    if check.fields["vin_status"] == "mismatch":
                        self._vin_mismatch(check)
                else:
                    self.outcomes.append(outcome)
                    self._identity_outcome(outcome)
                    if self.training is not None:
                        self.training.identity(
                            outcome.da, outcome.pgn, outcome.outcome, outcome.value
                        )
        if self.rawcap is not None:
            for fault in self.rawcap.take_faults():
                self._log(fault)
        if self.transmit is not None:
            for fault in self.transmit.take_faults():
                self.diag.log("error", "transmit", str(fault.fields.get("cause")))
                self._log(fault)

    def _vin_check(self, outcome: RequestOutcome) -> Record:
        vin = _vin_text(outcome.value) if outcome.outcome == "reply" else None
        self._vin_received = vin
        if vin is None:
            status = "unavailable"
        elif self._inventory_vin is None:
            status = "unavailable"  # nothing to compare with (untrained)
        else:
            status = "match" if vin == self._inventory_vin else "mismatch"
        self._vin_status = status
        return Record(
            "vin_check",
            "info",
            None,
            None,
            {
                "vin": vin,
                "vin_status": status,
                "inventory_vin": self._inventory_vin,
                "inventory": self._versions.get("inventory"),
                "outcome": outcome.outcome,
            },
        )

    # -- frames -------------------------------------------------------------------

    def _process(self, frames: list[Frame]) -> None:
        assert self.detect is not None
        self._frames_rx += len(frames)
        self._error_frames += sum(1 for f in frames if f.error)
        self._last_frame_mono = max(self._last_frame_mono, frames[-1].ts_mono)
        for f in frames:
            state = bus_state(f)
            if state is not None:
                self._bus_off = self._bus_off or state == "bus_off"
                if self.transmit is not None and self.transmit.enabled:
                    self.transmit.disable(state)  # NP-3
        msgs, stats, tx, self._decode_state = decode(
            frames, self._decode_state, logger_sa=self.logger_sa
        )
        self._decode_stats = stats
        if self.logger_sa is not None:
            self._submit((req, self.logger_sa) for req in tx)
        if self.rawcap is not None:
            self.rawcap.feed(frames)
        for msg in msgs:
            self._on_message(msg)

    def _on_message(self, msg: J1939Msg) -> None:
        assert self.detect is not None
        if self.address is not None:
            sends, records = self.address.on_message(msg)
            self._submit(sends)
            for record in records:
                self._log(record, msg.ts_mono)
        if self.requests is not None:
            self.requests.on_message(msg, self.logger_sa)
        for record in self.clock.on_time_date(msg) + self.detect.on_message(msg, self.logger_sa):
            self._log_detection(record, msg.ts_mono)
        if self.monitor is not None:  # after detect, so a new connection is already open
            conn, entry = self.detect.connection_for(msg.sa), self.detect.entry_for(msg.sa)
            for record in self.monitor.on_message(msg, conn, entry):
                if record.type == "control_flag" and record.conn is not None:
                    record.fields["raw_capture"] = self._raw_start(record.conn, msg.ts_mono)
                self._log(record, msg.ts_mono)
        if self.training is not None:
            self.training.observe(msg)

    def _log_detection(self, record: Record, ts_mono: Optional[float] = None) -> None:
        if record.type == "connection_end":
            self._final_identification(record)
        if record.type == "connection_start" and record.conn is not None:
            at = ts_mono if ts_mono is not None else self.clock.mono()
            record.fields["raw_capture"] = self._raw_start(record.conn, at)  # LOG-10
        self._log(record, ts_mono)
        if record.type != "connection_start":
            return
        if record.conn is not None and self.detect is not None:
            conn = next((c for c in self.detect.connections if c.conn == record.conn), None)
            if conn is not None and record.fields.get("category") != APPROVED:
                rule = str(record.fields.get("classification_rule", "wake timing"))
                self._idents[record.conn] = _Ident(conn, rule)
        self._connections_started += 1
        if self.eventlog is not None and not self._header_pending:
            self.eventlog.sync_now()  # DET-16
        if self.requests is not None and record.conn is not None:
            name = record.fields.get("name")
            value = int(name, 16) if isinstance(name, str) else None
            if self._dropped:
                value = None  # ask every device (NP-13 during training; DET-14 untrained)
            self.requests.identify(record.conn, int(record.fields["sa"]), value)

    @property
    def _untrained(self) -> bool:
        """Untrained (TRN-9): no inventory, or dropped for this session (DET-14, training)."""
        return self._inventory is None or self._dropped

    # -- new versions from the card (DC-20, DC-21) ------------------------------------

    def _set_inventory(self, inv: Optional[Inventory]) -> None:
        self._inventory = inv
        entries = inv.entries if inv is not None else ()
        self._inventory_addresses = tuple(a for e in entries for a in e.addresses)
        self._inventory_vin = inv.vin if inv is not None else None
        self._known_addresses = {
            a for e in entries if e.name is not None and e.category != APPROVED for a in e.addresses
        }
        self._versions["inventory"] = inv.version if inv is not None else None

    def _newest(self, kind: str) -> Optional[dict[str, Any]]:
        versions = self.store.versions(kind)
        if not versions:
            return None
        data = self.store.load(kind, versions[-1])
        try:
            doc = json.loads(data.decode("utf-8")) if data is not None else None
        except (ValueError, UnicodeDecodeError):
            return None
        return doc if isinstance(doc, dict) else None

    def _reload_from_card(self) -> None:
        """At session open: the newest saved inventory and config apply (or none after retrain)."""
        if not self._inventory_active:
            self._set_inventory(None)
        else:
            doc = self._newest("inventory")
            if doc is not None:
                inv = validate_inventory(doc)
                current = _version_number(self._inventory.version) if self._inventory else None
                new = _version_number(str(doc.get("inventory")))
                if isinstance(inv, Inventory) and (current is None or (new or 0) >= current):
                    self._set_inventory(inv)
        cfg_doc = self._newest("config")
        if cfg_doc is not None:
            cfg = validate(cfg_doc)
            if isinstance(cfg, Config) and cfg.version != self._versions.get("config"):
                self._settings = settings_from_config(cfg_doc)
                self._versions["config"] = cfg.version

    # -- status file and light (STS-1 to STS-3, DC-21) --------------------------------

    def _state_name(self) -> str:
        if self.eventlog is None or self._header_pending:
            return "starting"
        if self._bitrate is None:
            return "detecting bit rate"
        if self.training is not None:
            return "training"
        if self._untrained:
            return "needs training"
        if self._high_fault is not None:
            return "fault"
        return "recording"

    def status_state(self) -> State:
        try:
            usage = self.store.usage()
            pct: Optional[float] = usage.used_pct
        except OSError:
            pct = None
        reading = self.clock.now()
        transmit = "on"
        if self.transmit is not None and self.transmit.off_reason is not None:
            transmit = f"off: {self.transmit.off_reason}"
        elif self._guard_holds:
            transmit = "off: restart loop"
        retrieved = sorted({Path(f).name.split("_", 1)[0] for f in self._retrieved
                            if f.startswith("sessions/")})  # fmt: skip
        warn = float(self._settings.get("storage.warn_pct", 90))
        return State(
            state=self._state_name(),
            session=self._session or None,
            bitrate=self._bitrate,
            logger_sa=self.logger_sa,
            unreviewed_high=len(self._unreviewed),
            fault=self._high_fault,
            card_used_pct=pct,
            card_nearly_full=pct is not None and pct >= warn,
            clock_valid=reading.valid,
            clock_source=reading.source,
            untrained=self._untrained,
            retrieved=retrieved,
            training_coverage=self.training.coverage() if self.training is not None else None,
            config=self._versions.get("config"),
            inventory=self._versions.get("inventory"),
            library=self._versions.get("library"),
            transmit=transmit,
            vin_status=self._vin_status,
            restart_loop=self._guard_holds,
        )

    def _update_status(self, force: bool = False) -> None:
        now = self.clock.mono()
        if not force and now - self._status_mono < 0.5:
            return
        self._status_mono = now
        before = self.status.pattern
        data = self.status.update(self.status_state(), now, self._now_text())
        if self.status.pattern != before:
            self.diag.log("info", "status", f"light {self.status.pattern}")  # STS-1
        if data is not None:
            self.store.write_atomic("status", "status", data)

    # -- commands (STS-23, DC-21; cmdserver calls handle) ------------------------------

    CHANGING = frozenset(
        {
            "login",
            "logout",
            "train_start",
            "train_finish",
            "train_confirm",
            "approve",
            "remove",
            "clear",
            "config_push",
            "retrieved",
            "restart",
            "retrain",
        }
    )

    def handle(
        self,
        cmd: str,
        args: Optional[Mapping[str, Any]] = None,
        operator: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run one laptop command in the main loop; the protocol reply (``proto`` 1)."""
        args = dict(args or {})
        if cmd in self.CHANGING and not operator:
            return _refused("unknown operator key", "install the key with release/keys.sh")
        if self.eventlog is None and cmd not in ("status", "events", "inventory_show",
                                                 "config_show", "retrieve_list"):  # fmt: skip
            return _refused("no session is open", "wait for CAN activity, then retry")
        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler is None:
            return _refused(f"unknown command {cmd!r}", "run j1939ctl --help")
        try:
            result = handler(args, operator, reason)
        except InventoryRefused as exc:
            return _refused(str(exc), "check the ID with events or inventory show")
        except (ValueError, KeyError, TypeError) as exc:
            return _refused(f"bad arguments: {exc}", f"run j1939ctl {cmd} --help")
        self._update_status(force=True)
        return {"proto": 1, "ok": True, "result": result}

    def _need_reason(self, reason: Optional[str]) -> str:
        if not reason:
            raise InventoryRefused("a reason is required")
        return reason

    def _cmd_status(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        from j1939logger.status import contents

        body = contents(self.status_state(), self._now_text())
        body["vin"] = self._vin_received or self._inventory_vin
        body["unreviewed"] = list(self._unreviewed)
        return body

    def _cmd_login(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        fields = {"operator": operator, "connection": args.get("connection", "ssh"),
                  "tool_version": args.get("tool_version")}  # fmt: skip
        self._log(Record("operator_login", "notice", None, None, fields))
        return {"operator": operator}

    def _cmd_logout(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        fields = {"operator": operator, "connection": args.get("connection", "ssh"),
                  "tool_version": args.get("tool_version")}  # fmt: skip
        self._log(Record("operator_logout", "info", None, None, fields))
        return {"operator": operator}

    def _cmd_train_start(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        if self.training is not None:
            raise InventoryRefused("training is already running")
        self.train_start(str(operator))
        return {"timeout_min": self._settings["training.timeout_min"]}

    def _cmd_train_status(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        t = self.training
        if t is None:
            raise InventoryRefused("training is not running")
        elapsed = self.clock.mono() - t.start_mono
        total = float(self._settings["training.timeout_min"]) * 60.0
        return {"elapsed_s": round(elapsed), "remaining_s": max(0, round(total - elapsed)),
                "timed_out": t.timed_out, "coverage": t.coverage()}  # fmt: skip

    def _cmd_train_finish(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return self.train_finish(str(operator), bool(args.get("pto_declared", False)))

    def _cmd_train_confirm(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        version = self.confirm_inventory(str(operator), bool(args["apply"]), reason)
        if version is not None:
            self._inventory_active = True  # a confirmed training ends a retrain
            self._save_state()
        return {"inventory": version}

    def _event_rows(self, include_all: bool) -> list[dict[str, Any]]:
        rows = []
        wanted = set(self._unreviewed)
        for f in session_files(self._sessions_dir):
            for line in f.path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                eid = f"{f.session}-{r.get('rec')}"
                if r.get("type") in ("session_start", "session_end"):
                    continue
                if include_all or eid in wanted:
                    rows.append({"event": eid, "type": r.get("type"), "sev": r.get("sev"),
                                 "utc": r.get("utc"), "sa": r.get("sa"), "name": r.get("name"),
                                 "category": r.get("category"),
                                 "reviewed": eid not in wanted})  # fmt: skip
        return rows

    def _cmd_events(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"events": self._event_rows(bool(args.get("all", False)))}

    def _cmd_approve(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        event = str(args["event"])
        version = self.approve(event, str(operator), self._need_reason(reason),
                               bool(args.get("warning_shown", False)))  # fmt: skip
        if event in self._unreviewed:  # the approval clears its event (LAP-11)
            self._unreviewed.remove(event)
            self._save_state()
        return {"inventory": version, "cleared": [event]}

    def _cmd_remove(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        pgn = args.get("pgn")
        version = self.remove(str(args["entry"]), str(operator), self._need_reason(reason),
                              int(pgn) if pgn is not None else None, args.get("direction"),
                              bool(args.get("warning_shown", False)))  # fmt: skip
        return {"inventory": version}

    def _cmd_clear(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        events = [str(e) for e in args["events"]]
        why = self._need_reason(reason)
        not_open = [e for e in events if e not in self._unreviewed]
        if not events or not_open:
            raise InventoryRefused(
                f"not unreviewed high events: {', '.join(not_open) or 'none given'}"
            )
        for e in events:
            self._unreviewed.remove(e)
        self._save_state()
        from j1939logger.status import light

        after = light(self.status_state())
        self._log(Record("review_clear", "notice", None, None, {
            "operator": operator, "cleared": events, "disposition": args.get("disposition"),
            "reason": why, "approve_device": False, "light": after,
        }))  # fmt: skip
        return {"cleared": events, "light": after}

    def _cmd_config_show(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"config": self._newest("config")}

    def _cmd_config_push(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        new_doc = args["config"]
        old_doc = self._newest("config")
        old = validate(old_doc) if old_doc is not None else None
        if not isinstance(old, Config):
            raise InventoryRefused("the active config is not on the card")
        checked = validate(new_doc, old)
        proposed = new_doc.get("config") if isinstance(new_doc, Mapping) else None
        if isinstance(checked, ConfigError):
            self._log(rejected_record(checked, proposed, str(operator), None))
            raise InventoryRefused(f"config rejected: {checked}")
        if checked.version in [f"cfg-v{v}" for v in self.store.versions("config")]:
            raise InventoryRefused(f"{checked.version} already exists; raise the version")
        if checked.weakens and not args.get("confirm"):
            raise InventoryRefused(
                f"weakens detection ({', '.join(checked.weakens)}): add --confirm"
            )
        data = (json.dumps(new_doc, indent=2) + "\n").encode("utf-8")
        if not self.store.write_atomic("config", checked.version, data):
            raise InventoryRefused("the new config could not be saved")
        self._log(change_record(checked, old, str(operator), None))
        return {"config": checked.version, "changed": list(checked.changed),
                "weakens": list(checked.weakens)}  # fmt: skip

    def _cmd_inventory_show(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"inventory": self._inventory_doc()}

    def _cmd_retrieve_list(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"files": card_files(self._platform.paths().card)}

    def _cmd_retrieved(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        files = [str(f) for f in args.get("files", [])]
        for f in files:
            if f not in self._retrieved:
                self._retrieved.append(f)
        self._save_state()
        sessions = sorted({int(Path(f).name[1:7]) for f in files
                           if f.startswith("sessions/")
                           and Path(f).name[1:7].isdigit()})  # fmt: skip
        raw = [f for f in files if f.startswith("raw/")]
        partial = [self._session] if self._session in sessions else []
        self._log(Record("retrieval", "info", None, None, {
            "operator": operator, "sessions": sessions, "partial": partial, "raw_files": len(raw),
            "chain_verified": bool(args.get("chain")), "last_hash": args.get("last_hash"),
        }))  # fmt: skip
        return {"retrieved": len(files)}

    def _cmd_restart(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        self._log(reset_record("restart", str(operator), self._need_reason(reason)))
        self._unclean_starts = []  # an operator restart clears the restart guard (NP-19)
        self._save_state()
        self.exit_code = RESTART_EXIT
        self.stop()
        return {"exit_code": RESTART_EXIT}

    def _cmd_retrain(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        archived = self._versions.get("inventory")
        self._log(reset_record("retrain", str(operator), self._need_reason(reason), archived))
        self._inventory_active = False  # untrained from the next session (STS-12)
        self._save_state()
        return {"archived": archived}

    # -- raw captures and retention (step 6, DC-20) ---------------------------------

    def _raw_start(self, conn: int, ts_mono: float) -> Optional[str]:
        """Start a raw capture for an event; the name for ``raw_capture`` or None (LOG-10)."""
        if self.rawcap is None:
            return None
        before = self.capture.window(ts_mono - self.rawcap.before_s, ts_mono)
        return self.rawcap.start(conn, ts_mono, before)

    def _raw_poll(self) -> None:
        if self.rawcap is None:
            return
        if self.rawcap.poll(self.clock.mono()):
            self._retention()  # after each raw capture (DC-20)

    def _raw_files(self) -> list[RawFile]:
        folder = self._platform.paths().card / "raw"
        out = []
        for p in sorted(folder.glob("*.log")) if folder.is_dir() else []:
            try:
                st = p.stat()
            except OSError:
                continue
            done = f"raw/{p.name}" in self._retrieved  # retrieved first (LOG-11)
            out.append(RawFile(p, st.st_mtime, st.st_size, retrieved=done))
        return out

    def _retention(self) -> None:
        """Free raw captures when the card runs low; faults; stop captures at the reserve."""
        if self.retention is None:
            return
        try:
            usage = self.store.usage()
        except OSError:
            return
        plan = self.retention.check(usage, self._raw_files())
        if plan.free:
            self.store.free(plan.free)
        for fault in plan.faults:
            self._log(fault)
        if not plan.raw_allowed and self.rawcap is not None:
            self.rawcap.stop("card full; only the event reserve is left")  # LOG-22

    # -- VIN mismatch (DET-14) ------------------------------------------------------

    def _vin_mismatch(self, check: Record) -> None:
        self._log(
            Record(
                "vin_mismatch",
                "high",  # not capped (log-format severity rules)
                None,
                None,
                {
                    "vin": check.fields["vin"],
                    "inventory_vin": check.fields["inventory_vin"],
                    "inventory": check.fields["inventory"],
                    "logger_action": "rest of the session runs untrained",
                },
            )
        )
        self._drop_inventory()

    def _drop_inventory(self) -> None:
        self._dropped = True
        if self.detect is not None:
            self.detect.drop_inventory()
        if self.monitor is not None:
            self.monitor.drop_inventory()

    # -- operator calls (DC-20; step 7's cmdserver calls these) --------------------

    def _now_text(self) -> Optional[str]:
        return format_utc(self.clock.to_utc(self.clock.mono()))

    def _stored_inventories(self) -> list[dict[str, Any]]:
        out = []
        for v in self.store.versions("inventory"):
            data = self.store.load("inventory", v)
            try:
                doc = json.loads(data.decode("utf-8")) if data is not None else None
            except (ValueError, UnicodeDecodeError):
                doc = None
            if isinstance(doc, dict):
                out.append(doc)
        return out

    def _inventory_doc(self) -> Optional[dict[str, Any]]:
        """The inventory that operator changes build on: the newest saved version, so changes
        made in one session chain (each still applies from the next session), else the active
        inventory as an ``inv-1`` dict."""
        if self._inventory is None:
            return None
        active = _version_number(self._inventory.version)
        newest = None
        for doc in self._stored_inventories():
            n = _version_number(str(doc.get("inventory")))
            if n is not None and (newest is None or n > newest[0]):
                newest = (n, doc)
        if newest is not None and (active is None or newest[0] >= active):
            return newest[1]
        return {
            "format": "inv-1",
            "inventory": self._inventory.version,
            "vin": self._inventory.vin,
            "entries": [dict(e.raw) for e in self._inventory.entries],
        }

    def _next_inventory_version(self) -> str:
        numbers = set(self.store.versions("inventory"))
        if self._inventory is not None:
            m = re.match(r"^inv-v(\d+)$", self._inventory.version)
            if m:
                numbers.add(int(m.group(1)))
        if self._proposal is not None:
            m = re.match(r"^inv-v(\d+)$", str(self._proposal.get("inventory")))
            if m:
                numbers.add(int(m.group(1)))
        return next_version(numbers)

    def _write_inventory(self, doc: dict[str, Any]) -> bool:
        """Save a new version through store; it applies from the next session (DC-20)."""
        data = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        return self.store.write_atomic("inventory", str(doc["inventory"]), data)

    def train_start(self, operator: str) -> None:
        """Start training (TRN-2): observe every device; this session runs untrained."""
        if self.eventlog is None or self.detect is None:
            raise InventoryRefused("no session is open")
        now = self.clock.mono()
        self.training = Training(self._settings, now, self._logger_name, operator)
        for sa in range(254):  # NAMEs already claimed this session
            name = self.detect.name_at(sa)
            if name is not None:
                data = name.to_bytes(8, "little")
                self.training.observe(
                    J1939Msg(now, 0.0, 6, 60928, sa, 255, data, False, False, False)
                )
        self._proposal = None
        self._drop_inventory()  # detection runs as in untrained mode during training
        self._log(
            Record(
                "training_start",
                "notice",
                None,
                None,
                {"operator": operator, "states": list(self._settings["training.states"])},
            )
        )

    def train_finish(self, operator: str, pto_declared: bool = False) -> dict[str, Any]:
        """Stop training and return the proposed inventory; not applied until confirmed (TRN-4)."""
        if self.training is None:
            raise InventoryRefused("training is not running")
        t = self.training
        t.observing(self.clock.mono())
        timed_out = t.timed_out
        t.stopped = True
        lib = self.library.manufacturers if self.library is not None else None
        proposal = t.propose(
            previous=self._inventory_doc(),
            stored=self._stored_inventories(),
            version=self._next_inventory_version(),
            vin=self._vin_received,
            session=self._session,
            now_utc=self._now_text(),
            manufacturers=lib,
            pto_declared=pto_declared,
        )
        coverage = t.coverage(pto_declared)
        self._log(
            Record(
                "training_finish",
                "notice",
                None,
                None,
                {
                    "operator": operator,
                    "states_covered": coverage["conditions"],
                    "inventory_proposed": proposal["inventory"],
                    "coverage": coverage,
                    "timed_out": timed_out,
                },
            )
        )
        self.training = None
        self._proposal = proposal
        return proposal

    def confirm_inventory(
        self, operator: str, apply: bool, reason: Optional[str] = None
    ) -> Optional[str]:
        """Apply (save) or reject the proposed inventory; the new version, or None (TRN-4)."""
        if self._proposal is None:
            raise InventoryRefused("no proposed inventory")
        proposal, self._proposal = self._proposal, None
        if not apply:
            self._log(rejection_record(proposal, operator, reason))
            return None
        if not self._write_inventory(proposal):
            raise InventoryRefused("the new inventory could not be saved")
        self._log(confirm_record(proposal, operator, reason))
        return str(proposal["inventory"])

    def _find_event(self, event_id: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
        """The logged record for ``session-rec``, and its connection_end if it has one."""
        m = re.match(r"^(\d+)-(\d+)$", event_id)
        if m is None:
            raise InventoryRefused(f"bad event ID {event_id}")
        session, rec = int(m.group(1)), int(m.group(2))
        records: list[dict[str, Any]] = []
        for f in session_files(self._sessions_dir):
            if f.session != session:
                continue
            for line in f.path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue  # an incomplete last line
        event = next((r for r in records if r.get("rec") == rec), None)
        if event is None:
            raise InventoryRefused(f"event {event_id} not found")
        end = None
        if event.get("type") == "connection_start":
            end = next(
                (
                    r
                    for r in records
                    if r.get("type") == "connection_end" and r.get("conn") == event.get("conn")
                ),
                None,
            )
        return event, end

    def approve(
        self, event_id: str, operator: str, reason: str, warning_shown: bool = False
    ) -> str:
        """Approve a logged device, new PGN or address change (TRN-5, TRN-10); the new version."""
        doc = self._inventory_doc()
        if doc is None:
            raise InventoryRefused("no inventory to approve into (untrained)")
        event, end = self._find_event(event_id)
        version = self._next_inventory_version()
        new, record = approve(
            doc,
            event,
            event_id=event_id,
            end=end,
            stored=self._stored_inventories(),
            version=version,
            operator=operator,
            reason=reason,
            session=self._session,
            now_utc=self._now_text(),
            warning_shown=warning_shown,
            control_pgns=self._settings["detection.control_pgns"],
        )
        if not self._write_inventory(new):
            raise InventoryRefused("the new inventory could not be saved")
        self._log(record)
        return version

    def remove(
        self,
        entry_id: str,
        operator: str,
        reason: str,
        pgn: Optional[int] = None,
        direction: Optional[str] = None,
        warning_shown: bool = False,
    ) -> str:
        """Remove an entry or one of its PGNs (TRN-14, TRN-15); the new version."""
        doc = self._inventory_doc()
        if doc is None:
            raise InventoryRefused("no inventory to remove from (untrained)")
        version = self._next_inventory_version()
        new, record = remove(
            doc,
            entry_id,
            version=version,
            operator=operator,
            reason=reason,
            session=self._session,
            now_utc=self._now_text(),
            pgn=pgn,
            direction=direction,
            warning_shown=warning_shown,
        )
        if not self._write_inventory(new):
            raise InventoryRefused("the new inventory could not be saved")
        self._log(record)
        return version

    # -- identification (step 5, DC-17) -------------------------------------------

    def _classify(
        self, name: Optional[Name], since_s: float, what: str
    ) -> tuple[str, str, str, str]:
        return classify(
            name,
            since_s,
            wake_window_s=float(self._settings["classify.wake_window_s"]),
            trailer_vehicle_system=int(self._settings["classify.trailer_vehicle_system"]),
            untrained=self._untrained,
            what=what,
        )

    def _end_summary(self, conn: int) -> Mapping[str, Any]:
        """monitor.end, keeping the requested PGNs for the final identification."""
        assert self.monitor is not None
        self._end_sets[conn] = self.monitor.requested_pgns(conn)
        return self.monitor.end(conn)

    def _identity_outcome(self, outcome: RequestOutcome) -> None:
        state = self._idents.get(outcome.conn) if outcome.conn is not None else None
        if state is None or state.ident is not None:
            return
        state.outcomes.append(outcome)
        if len(state.outcomes) >= IDENTITY_REQUESTS:  # all identity requests answered
            self._identify(state)

    def _run_identify(
        self,
        state: _Ident,
        requested: frozenset[int],
        sent: set[int],
        ended_before_session: bool = False,
    ) -> Identification:
        reason = reclassify(
            state.conn.category,
            requested=requested,
            sent=sent,
            control_pgns=self._settings["detection.control_pgns"],
            claimed_known_address=state.conn.sa in self._known_addresses,
            ended_before_session=ended_before_session,
        )
        return identify(
            state.conn,
            state.outcomes,
            requested,
            self.library,
            tie_margin=float(self._settings["identify.tie_margin"]),
            sent=sent,
            classification_rule=state.rule,
            reclassified=reason,
            untrained=self._untrained,
        )

    def _identify(self, state: _Ident) -> None:
        """The identification record once the identity requests are answered (IDN-3, IDN-4)."""
        assert self.monitor is not None
        conn = state.conn.conn
        sent = {int(p["pgn"]) for p in self.monitor.summary(conn).get("pgns_sent", [])}
        state.ident = self._run_identify(state, self.monitor.requested_pgns(conn), sent)
        self._log(identification_record(state.conn, state.ident, state.outcomes, self.clock.to_utc))

    def _final_identification(self, record: Record) -> None:
        """Recalculate at connection end; final_identification if it changed (IDN-4, DC-17)."""
        state = self._idents.pop(record.conn, None) if record.conn is not None else None
        requested = self._end_sets.pop(record.conn, frozenset()) if record.conn else frozenset()
        if state is None:
            return
        sent = {int(p["pgn"]) for p in record.fields.get("pgns_sent", [])}
        early = record.fields.get("end_reason") == "silence"
        final = self._run_identify(state, requested, sent, ended_before_session=early)
        if state.ident is None:  # ended before its identity requests were answered
            state.ident = final
            self._log(identification_record(state.conn, final, state.outcomes, self.clock.to_utc))
        elif final.changed_from(state.ident) or final.category != state.ident.category:
            record.fields["final_identification"] = identification_fields(
                final, state.outcomes, self.clock.to_utc
            )
        record.sev = final.sev  # connection_end takes the final severity (DC-17)

    def _detection(self) -> None:
        """The first-sweep signals and detect's timed checks (DET-2, DET-4, DET-6)."""
        if self.detect is None:
            return
        now = self.clock.mono()
        if self.detect.waiting:
            if self.requests is not None and self.requests.first_sweep_done:
                for record in self.detect.sweep_complete(now):
                    self._log_detection(record)
            elif not self._no_sweep_sent and self._no_sweep_possible(now):
                self._no_sweep_sent = True
                self.detect.no_sweep()
        for record in self.detect.poll(now):
            self._log_detection(record)

    def _no_sweep_possible(self, now: float) -> bool:
        """No sweep can be sent this session: no bit rate yet, transmit off, or claim lost."""
        if self._guard_holds or (self.address is not None and self.address.lost):
            return True
        if self.transmit is not None and self.transmit.off_reason is not None:
            return True  # bus-off, error-passive or a breach (NP-3, NP-18)
        wait_s = float(self._settings["detection.first_sweep_wait_s"])
        return self._bitrate is None and now - self._open_mono >= wait_s

    def _end_connections(self, reason: str) -> None:
        """connection_end for every open connection, before session_end (DET-6)."""
        if self.detect is None:
            return
        for record in self.detect.end_all(reason, self.clock.mono()):
            self._log_detection(record)

    def _timers(self) -> None:
        if self.eventlog is None:
            return
        now = self.clock.mono()
        if now - self._last_frame_mono >= float(self._get("session.end_silence_s", 30)):
            self._close_session("key-off, bus silent")  # LOG-17
            return
        rollover_s = float(self._get("logging.session_rollover_h", 24)) * 3600.0
        if now - self._part_start_mono >= rollover_s:
            self._roll_over()  # LOG-2

    # -- records ------------------------------------------------------------------

    def _log(self, record: Record, ts_mono: Optional[float] = None) -> None:
        assert self.eventlog is not None
        t = self.clock.mono() if ts_mono is None else ts_mono
        if record.utc is None:
            record.utc = self.clock.to_utc(t)
        if record.veh_time is None:
            record.veh_time = self.clock.veh_time(t)
        if self._header_pending and record.type != "session_start":
            self._buffer.append((record, ts_mono))
            return
        event_id = self.eventlog.append(record)
        if event_id is not None:
            self._counts[record.sev] = self._counts.get(record.sev, 0) + 1
            if record.sev == "high":
                self._unreviewed.append(event_id)  # until cleared (STS-2)
                if record.type == "fault":
                    self._high_fault = str(record.fields.get("cause"))
                self._save_state()

    def _drain_faults(self) -> None:
        faults = self.store.take_faults()
        if self.eventlog is not None:
            faults += self.eventlog.take_faults()
        for f in faults:
            self.diag.log("error", "storage", str(f.fields.get("cause")))
            if self.eventlog is not None:
                self._log(f)

    # -- opening ------------------------------------------------------------------

    def _reset_counts(self) -> None:
        self._counts = {"high": 0, "notice": 0, "info": 0}
        self._frames_rx = 0
        self._error_frames = 0
        self._decode_state = new_state(int(self._settings["limits.tp_sessions"]))
        self._decode_stats = self._decode_state.stats
        self._last_frame_mono = self.clock.mono()
        self._part_start_mono = self.clock.mono()

    def _read_state(self) -> tuple[Optional[dict[str, Any]], bool]:
        """(state, corrupt) from state.json on internal flash."""
        raw = self.store.load("state")
        if raw is None:
            return None, False
        try:
            state = json.loads(raw)
            if state.get("format") != STATE_FORMAT or not isinstance(state.get("session"), int):
                raise ValueError("bad state.json")
            return state, False
        except (ValueError, AttributeError):
            return None, True

    def _write_state(self, session: int) -> None:
        assert self.eventlog is not None
        state = {
            "format": STATE_FORMAT,
            "logger_id": self._get("address.name", None),
            "session": session,
            "last_hash": self.eventlog.last_hash,
            "unclean_starts": self._unclean_starts,
            "unreviewed": self._unreviewed,
            "retrieved": self._retrieved,
            "inventory_active": self._inventory_active,
        }
        self.store.write_atomic("state", "state", json.dumps(state).encode("utf-8"))

    def _save_state(self) -> None:
        if self.eventlog is not None:
            self._write_state(self._session)

    def _restart_guard(self, unclean: bool) -> bool:
        """Record an unclean start and say whether the restart guard holds (NP-19)."""
        now = self.clock.now().wall_utc
        if unclean:
            self._unclean_starts.append(format_utc(now))
        window_s = float(self._get("restart_guard.window_min", 10)) * 60.0
        recent: list[Optional[str]] = []
        for t in self._unclean_starts:
            if t is None or now is None:
                recent.append(t)  # without a valid time, an entry counts as recent
                continue
            when = datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            if (now - when).total_seconds() <= window_s:
                recent.append(t)
        self._unclean_starts = recent
        return len(recent) >= int(self._get("restart_guard.count", 3))

    def _open_session(self, wake: str) -> None:
        self._reset_counts()
        prev_info: dict[str, Any] = {
            "prev_session": None,
            "prev_session_end": None,
            "prev_end_cause": None,
            "bytes_cut_off": 0,
        }
        new_card = False
        notices: list[str] = []
        unclean = False
        if self._first_open:
            files = session_files(self._sessions_dir)
            state, corrupt = self._read_state()
            starts = state.get("unclean_starts") if state else None
            self._unclean_starts = list(starts) if isinstance(starts, list) else []
            if state:
                self._unreviewed = [str(x) for x in state.get("unreviewed", []) or []]
                self._retrieved = [str(x) for x in state.get("retrieved", []) or []]
                self._inventory_active = state.get("inventory_active", True) is not False
            newest = files[-1] if files else None
            card_last = newest.session if newest else 0
            state_last = state["session"] if state else 0
            self._next_session = max(card_last, state_last) + 1
            if newest is not None:
                tail = scan_tail(newest.path)
                self._prev_hash = tail.last_hash or ZERO_HASH
                if tail.last_hash is None:
                    # The newest file has no complete record (power lost before its
                    # header): the chain continues from the newest file that has one.
                    for older in reversed(files[:-1]):
                        older_tail = scan_tail(older.path)
                        if older_tail.last_hash is not None:
                            self._prev_hash = older_tail.last_hash
                            break
                if tail.last_type == "session_end" and tail.bytes_cut_off == 0:
                    end, cause = "clean", None
                else:
                    cause = self.diag.last_restart_cause()
                    end = cause or "power loss"
                    unclean = True
                prev_info = {
                    "prev_session": newest.session,
                    "prev_session_end": end,
                    "prev_end_cause": cause,
                    "bytes_cut_off": tail.bytes_cut_off,
                }
            else:
                self._prev_hash = ZERO_HASH
                new_card = state is not None
            if corrupt:
                notices.append("state.json corrupt; numbering from the card")
            self._first_open = False
        elif self._next_session > 1:
            prev_info["prev_session"] = self._next_session - 1
            prev_info["prev_session_end"] = "clean"
        self._guard_holds = self._restart_guard(unclean)
        session = self._next_session
        self._next_session += 1
        self._session = session
        self._part = 1
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._stamp = self._time_stamp()
        self.eventlog = EventLog(
            self._platform, self.clock, self._part_path(), session, self._prev_hash
        )
        self._reload_from_card()
        self.monitor = Monitor(self.clock, self._settings, self._inventory)
        self.detect = Detect(
            self.clock,
            self._settings,
            self._inventory,
            self._end_summary,
            self.clock.mono(),
            classify=self._classify,
        )
        self._idents = {}
        self._end_sets = {}
        self._high_fault = None
        self._vin_status = None
        self._dropped = False
        self._vin_received = None
        self.rawcap = RawCap(self._platform, self._settings, session)
        self.retention = Retention(self._settings)
        self._no_sweep_sent = False
        self._connections_started = 0
        self.transmit = Transmit(self._platform, self.clock, self._settings, self._logger_name)
        self.address = Address(
            self.clock, self._settings, self._logger_name, self._inventory_addresses
        )
        known = set(self._inventory.by_name()) if self._inventory is not None else set()
        self.requests = Requests(
            self.clock, self._settings, known, self._logger_name, self.transmit.release
        )
        self._bitrate = None
        self._bitrate_fault_logged = False
        self._claim_sent_mono = None
        self._bus_off = False
        self._open_mono = self.clock.mono()
        self._wake = wake
        self._prev_info = prev_info
        self._new_card = new_card
        self._header_pending = True
        self._buffer = []
        for message in notices:
            self._log(
                Record(
                    "fault", "notice", None, None, {"cause": message, "logger_action": "continued"}
                )
            )
        for message in self._startup_faults:
            self._log(
                Record(
                    "fault",
                    "high",
                    None,
                    None,
                    {"cause": message, "logger_action": "running untrained"},
                )
            )
        self._startup_faults = []
        if self._library_fault is not None:
            self._log(
                Record(
                    "fault",
                    "high",
                    None,
                    None,
                    {"cause": self._library_fault, "logger_action": "identifying without it"},
                )
            )
            self._library_fault = None  # once, in the first session (DC-19)
        if self._guard_holds:
            self._log(
                Record(
                    "fault",
                    "high",
                    None,
                    None,
                    {
                        "cause": "restart loop; transmit disabled",
                        "logger_action": "listen-only until an operator runs restart",
                    },
                )
            )
        self.eventlog.start_sync(float(self._get("logging.sync_interval_s", 2)))
        self._try_bitrate()
        self._settle_header()
        self._write_state(session)
        self._retention()  # at session start (DC-20)
        self.diag.log("info", "session", f"session {session} started ({wake})")

    def _settle_header(self) -> None:
        """Write session_start once the claim has settled, then the records held for it."""
        if not self._header_pending or self.eventlog is None:
            return
        if self._claim_sent_mono is not None and not (self.address and self.address.lost):
            wait_s = float(self._get("address.claim_wait_ms", 250)) / 1000.0
            if self.clock.mono() < self._claim_sent_mono + wait_s:
                return
        self._header_pending = False
        self._log(self._session_start())
        held, self._buffer = self._buffer, []
        for record, ts in held:
            self._log(record, ts)
        self.eventlog.sync_now()

    def _time_stamp(self) -> str:
        wall = self.clock.now().wall_utc
        return wall.strftime("%Y%m%dT%H%M%SZ") if wall is not None else "noclock"

    def _part_path(self) -> Path:
        suffix = "" if self._part == 1 else f"_p{self._part}"
        return self._sessions_dir / f"s{self._session:06d}_{self._stamp}{suffix}.jsonl"

    def _claim_text(self) -> str:
        if self._guard_holds:
            return "not claimed (restart guard: transmit disabled)"
        if self._bitrate is None:
            return "not claimed (bit rate not confirmed)"
        if self.transmit is not None and self.transmit.off_reason is not None:
            return f"not claimed (transmit off: {self.transmit.off_reason})"
        if self.address is not None and self.address.lost:
            return "Cannot Claim; receive-only for the session"
        if self.logger_sa is not None:
            return f"ok after {int(self._get('address.claim_wait_ms', 250))} ms"
        return "not claimed"

    def _session_start(self) -> Record:
        wake_mono, ready_mono = self._platform.on_wake()
        keys_dir = self._platform.paths().keys
        keys = sorted(p.stem for p in keys_dir.glob("*.pub")) if keys_dir.is_dir() else []
        asking = self.transmit is not None and self.transmit.enabled and self.logger_sa is not None
        fields: dict[str, Any] = {
            "format": LOG_FORMAT,
            "session": self._session,
            "part": self._part,
            "sw": SW_VERSION,
            "config": self._versions.get("config"),
            "inventory": self._versions.get("inventory"),
            "library": self._versions.get("library"),
            "vin": None,
            "vin_status": "pending" if asking else "unavailable",  # DC-12
            "wake": self._wake,
            "ready_s": round(ready_mono - wake_mono, 3),
            "bitrate": self._bitrate,
            "bitrate_check": "confirmed by the platform" if self._bitrate else "not confirmed",
            "rx_buffer_actual_bytes": self.capture.stats().rx_buffer_bytes,
            "connector": self._get("install.connector", None),
            "network": self._get("install.network", None),
            **self._prev_info,
            "logger_sa": self.logger_sa,
            "logger_name": self._get("address.name", None),
            "logger_claim": self._claim_text(),
            "new_card": self._new_card,
            "restart_guard": "triggered; transmit disabled"
            if self._guard_holds
            else "not triggered",
            "operator_keys": keys,
            "untrained": self._untrained,
            "raw_dir": "raw/",
        }
        return Record("session_start", "info", None, None, fields)

    # -- closing ------------------------------------------------------------------

    def _session_end(self, reason: str) -> Record:
        cap = self.capture.stats()
        non = self._decode_stats.non_j1939
        try:
            card_pct: Optional[float] = self.store.usage().used_pct
        except OSError:
            card_pct = None
        connections = self._connections_started
        tx = (
            self.transmit.logger_tx()
            if self.transmit is not None
            else {"claims": 0, "requests": 0, "tp_cts": 0, "tp_eoma": 0, "nacks": 0}
        )
        fields = {
            "reason": reason,
            "connections": connections,
            "counts": dict(self._counts),
            "frames_rx": self._frames_rx,
            "bus_errors": self._error_frames,
            "bus_off": self._bus_off,
            "kernel_drops": cap.kernel_drops,
            "frames_not_j1939": {
                "std_11bit": non.get("standard", 0),  # DC-10
                "remote": non.get("remote", 0),
                "error": non.get("error", 0),
            },
            "logger_tx": tx,
            "sweeps": self.requests.sweeps if self.requests is not None else 0,
            "sweeps_logged": "first and changes only",
            "card_used_pct": card_pct,
        }
        return Record("session_end", "info", None, None, fields)

    def _close_session(self, reason: str) -> None:
        assert self.eventlog is not None
        if self._header_pending:
            self._claim_sent_mono = None
            self._settle_header()
        self._collect()
        self._end_connections(CONNECTION_END_REASON.get(reason, "software restart"))
        if self.rawcap is not None:
            self.rawcap.close()  # open captures with what they have
            for fault in self.rawcap.take_faults():
                self._log(fault)
        self._log(self._session_end(reason))
        self.eventlog.sync_now()
        self.eventlog.close()
        self._prev_hash = self.eventlog.last_hash
        self._unclean_starts = []  # a clean end clears the restart guard (NP-19)
        self._write_state(self._session)
        self.diag.log("info", "session", f"session {self._session} ended ({reason})")
        self.diag.flush()
        self.eventlog = None
        self.detect = None
        self.monitor = None
        self.rawcap = None
        self.retention = None
        self.training = None
        self.transmit = None
        self.address = None
        self.requests = None

    def _roll_over(self) -> None:
        assert self.eventlog is not None
        self._end_connections("session roll-over")
        self._log(self._session_end("session roll-over"))
        self.eventlog.sync_now()
        self._part += 1
        self.eventlog.roll_over(self._part_path())
        self._part_start_mono = self.clock.mono()
        self._counts = {"high": 0, "notice": 0, "info": 0}  # each part reports its own counts
        self._connections_started = 0
        self._frames_rx = 0
        self._error_frames = 0
        self._wake = "session roll-over"
        self._log(self._session_start())
        self.eventlog.sync_now()
        self._write_state(self._session)
        self.diag.log("info", "session", f"session {self._session} part {self._part} started")
