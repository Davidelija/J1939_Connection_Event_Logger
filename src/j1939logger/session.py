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

import json
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.address import Address
from j1939logger.admin import DiagLog
from j1939logger.capture import Capture
from j1939logger.clock import Clock
from j1939logger.decode import bus_state, decode, new_state
from j1939logger.detect import Detect, InventoryEntry
from j1939logger.eventlog import ZERO_HASH, EventLog, format_utc, scan_tail
from j1939logger.platform.interface import Platform
from j1939logger.requests import PGN_VIN, RequestOutcome, Requests
from j1939logger.store import Store
from j1939logger.transmit import Transmit
from j1939logger.types import Frame, J1939Msg, PlatformError, Record, TxRequest

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


class Session:
    def __init__(
        self,
        platform: Platform,
        settings: Mapping[str, Any],
        inventory: Optional[Mapping[int, InventoryEntry]],
        versions: Optional[Mapping[str, Optional[str]]] = None,
        startup_faults: Optional[list[str]] = None,
        inventory_addresses: Iterable[int] = (),
        inventory_vin: Optional[str] = None,
    ) -> None:
        self._platform = platform
        self._settings = settings
        self._inventory = inventory
        self._inventory_addresses = tuple(inventory_addresses)
        self._inventory_vin = inventory_vin
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
        self.transmit: Optional[Transmit] = None
        self.address: Optional[Address] = None
        self.requests: Optional[Requests] = None
        self.outcomes: list[RequestOutcome] = []  # identity outcomes, for identify (step 5)
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
        """Power-on: open capture listen-only and open the first session."""
        self.capture.start(listen_only=True)
        self._open_session(wake="power-on")

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
            if self.eventlog is not None:
                self._close_session(
                    "service stopped" if error is None else f"stopped: {error.kind}"
                )
            self.diag.flush()
        return error

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
                    self._log(self._vin_check(outcome))
                else:
                    self.outcomes.append(outcome)
        if self.transmit is not None:
            for fault in self.transmit.take_faults():
                self.diag.log("error", "transmit", str(fault.fields.get("cause")))
                self._log(fault)

    def _vin_check(self, outcome: RequestOutcome) -> Record:
        vin = _vin_text(outcome.value) if outcome.outcome == "reply" else None
        if vin is None:
            status = "unavailable"
        elif self._inventory_vin is None:
            status = "unavailable"  # nothing to compare with (untrained)
        else:
            status = "match" if vin == self._inventory_vin else "mismatch"
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
        for record in self.clock.on_time_date(msg) + self.detect.on_message(msg):
            self._log(record, msg.ts_mono)
            if record.type == "connection_start":
                if self.eventlog is not None and not self._header_pending:
                    self.eventlog.sync_now()  # DET-16
                if self.requests is not None and record.conn is not None:
                    name = record.fields.get("name")
                    value = int(name, 16) if isinstance(name, str) else None
                    self.requests.identify(record.conn, int(record.fields["sa"]), value)

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
        if self.eventlog.append(record) is not None:
            self._counts[record.sev] = self._counts.get(record.sev, 0) + 1

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
        }
        self.store.write_atomic("state", "state", json.dumps(state).encode("utf-8"))

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
        self.detect = Detect(
            self.clock, self._inventory, float(self._settings["classify.wake_window_s"])
        )
        self.transmit = Transmit(self._platform, self.clock, self._settings, self._logger_name)
        self.address = Address(
            self.clock, self._settings, self._logger_name, self._inventory_addresses
        )
        known = set(self._inventory) if self._inventory is not None else set()
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
            "untrained": self._inventory is None,
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
        connections = len(self.detect.connections) if self.detect is not None else 0
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
        self.transmit = None
        self.address = None
        self.requests = None

    def _roll_over(self) -> None:
        assert self.eventlog is not None
        self._log(self._session_end("session roll-over"))
        self.eventlog.sync_now()
        self._part += 1
        self.eventlog.roll_over(self._part_path())
        self._part_start_mono = self.clock.mono()
        self._counts = {"high": 0, "notice": 0, "info": 0}  # each part reports its own counts
        self._frames_rx = 0
        self._error_frames = 0
        self._wake = "session roll-over"
        self._log(self._session_start())
        self.eventlog.sync_now()
        self._write_state(self._session)
        self.diag.log("info", "session", f"session {self._session} part {self._part} started")
