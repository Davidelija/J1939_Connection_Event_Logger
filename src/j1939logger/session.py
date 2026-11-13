"""session: the session lifecycle and the main loop (docs/modules.md section 4, contract v1).

Layer 4; frozen for step 2. Listen-only throughout until transmit arrives in
step 3.

Lifecycle:

* ``start()`` (power-on) opens capture listen-only and opens a session.
* Each ``step()`` kicks the watchdog (STS-18), reads frames, and runs
  ``decode`` -> ``clock`` (Time/Date) -> ``detect`` -> ``eventlog``; a
  ``connection_start`` is synced at once (DET-16).
* Key-off: after ``session.end_silence_s`` with no frames the session ends
  with ``session_end`` (reason "key-off, bus silent", LOG-17); the next frame
  opens a new session with wake cause "CAN activity" (DC-10).
* Roll-over: after ``logging.session_rollover_h`` the part ends with
  ``session_end`` (reason "session roll-over") and the next part starts with a
  repeated ``session_start``; record numbers and the chain continue (LOG-2,
  DC-10, DC-11).
* ``stop()`` ends the open session cleanly (reason "service stopped").

Numbering and the chain (LOG-5, DC-10): the next session number is one more
than the higher of ``state.json`` and the newest session file on the card. The
first ``prev`` is the hash of the last complete line of the newest session
file; with no session files it is 64 zeros, and a card with no sessions but a
state file is a new card (``new_card: true``). ``state.json`` is written at
each session start and after each part.

Previous session end (LOG-12, LOG-18, DC-10): clean if the newest session file
ends with ``session_end``; otherwise the restart cause in the diagnostic log;
otherwise power loss, with the bytes of any incomplete last line.

Placeholders until later steps (DC-11): VIN, logger address and claim,
restart guard, operator keys.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from j1939logger.admin import DiagLog
from j1939logger.capture import Capture
from j1939logger.clock import Clock
from j1939logger.decode import decode, new_state
from j1939logger.detect import Detect, InventoryEntry
from j1939logger.eventlog import ZERO_HASH, EventLog, scan_tail
from j1939logger.platform.interface import Platform
from j1939logger.store import Store
from j1939logger.types import PlatformError, Record

__all__ = ["Session", "settings_from_config", "SessionFile", "session_files", "SW_VERSION"]

SW_VERSION = "0.0.0"
LOG_FORMAT = "log-1"
STATE_FORMAT = "state-1"

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


class Session:
    def __init__(
        self,
        platform: Platform,
        settings: Mapping[str, Any],
        inventory: Optional[Mapping[int, InventoryEntry]],
        versions: Optional[Mapping[str, Optional[str]]] = None,
        startup_faults: Optional[list[str]] = None,
    ) -> None:
        self._platform = platform
        self._settings = settings
        self._inventory = inventory
        self._versions = dict(versions or {})
        self._startup_faults = list(startup_faults or [])
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
        self._decode_state = new_state(int(settings["limits.tp_sessions"]))
        self._decode_stats = self._decode_state.stats
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

    def step(self, max_n: int = 1000) -> int:
        """Process the frames already received and the session timers; returns frame count."""
        self._platform.watchdog_kick()
        frames = self.capture.read_batch(max_n)
        if frames and self.eventlog is None:
            self._open_session(wake="CAN activity")
        if frames:
            self._process(frames)
        self._timers()
        self._drain_faults()
        return len(frames)

    # -- frames -------------------------------------------------------------------

    def _process(self, frames: list[Any]) -> None:
        assert self.detect is not None
        self._frames_rx += len(frames)
        self._error_frames += sum(1 for f in frames if f.error)
        self._last_frame_mono = max(self._last_frame_mono, frames[-1].ts_mono)
        msgs, stats, _, self._decode_state = decode(frames, self._decode_state, logger_sa=None)
        self._decode_stats = stats
        for msg in msgs:
            for record in self.clock.on_time_date(msg) + self.detect.on_message(msg):
                self._log(record, msg.ts_mono)
                if record.type == "connection_start" and self.eventlog is not None:
                    self.eventlog.sync_now()  # DET-16

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
        }
        self.store.write_atomic("state", "state", json.dumps(state).encode("utf-8"))

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
        if self._first_open:
            files = session_files(self._sessions_dir)
            state, corrupt = self._read_state()
            newest = files[-1] if files else None
            card_last = newest.session if newest else 0
            state_last = state["session"] if state else 0
            self._next_session = max(card_last, state_last) + 1
            if newest is not None:
                tail = scan_tail(newest.path)
                self._prev_hash = tail.last_hash or ZERO_HASH
                if tail.last_type == "session_end" and tail.bytes_cut_off == 0:
                    end, cause = "clean", None
                else:
                    cause = self.diag.last_restart_cause()
                    end = cause or "power loss"
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
        self._wake = wake
        self._prev_info = prev_info
        self._new_card = new_card
        self._log(self._session_start())
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
        self.eventlog.sync_now()
        self.eventlog.start_sync(float(self._get("logging.sync_interval_s", 2)))
        self._write_state(session)
        self.diag.log("info", "session", f"session {session} started ({wake})")

    def _time_stamp(self) -> str:
        wall = self.clock.now().wall_utc
        return wall.strftime("%Y%m%dT%H%M%SZ") if wall is not None else "noclock"

    def _part_path(self) -> Path:
        suffix = "" if self._part == 1 else f"_p{self._part}"
        return self._sessions_dir / f"s{self._session:06d}_{self._stamp}{suffix}.jsonl"

    def _session_start(self) -> Record:
        wake_mono, ready_mono = self._platform.on_wake()
        bitrate = self._platform.bitrate_check()
        keys_dir = self._platform.paths().keys
        keys = sorted(p.stem for p in keys_dir.glob("*.pub")) if keys_dir.is_dir() else []
        fields: dict[str, Any] = {
            "format": LOG_FORMAT,
            "session": self._session,
            "part": self._part,
            "sw": SW_VERSION,
            "config": self._versions.get("config"),
            "inventory": self._versions.get("inventory"),
            "library": self._versions.get("library"),
            "vin": None,
            "vin_status": "unavailable",
            "wake": self._wake,
            "ready_s": round(ready_mono - wake_mono, 3),
            "bitrate": bitrate,
            "bitrate_check": "reported by the platform (frame check in step 3)"
            if bitrate
            else "not confirmed",
            "rx_buffer_actual_bytes": self.capture.stats().rx_buffer_bytes,
            "connector": self._get("install.connector", None),
            "network": self._get("install.network", None),
            **self._prev_info,
            "logger_sa": None,
            "logger_name": self._get("address.name", None),
            "logger_claim": "not claimed (transmit starts in step 3)",
            "new_card": self._new_card,
            "restart_guard": "not checked (step 3)",
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
        fields = {
            "reason": reason,
            "connections": connections,
            "counts": dict(self._counts),
            "frames_rx": self._frames_rx,
            "bus_errors": self._error_frames,
            "bus_off": False,
            "kernel_drops": cap.kernel_drops,
            "frames_not_j1939": {
                "std_11bit": non.get("standard", 0),  # DC-10
                "remote": non.get("remote", 0),
                "error": non.get("error", 0),
            },
            "logger_tx": {"claims": 0, "requests": 0, "tp_cts": 0, "tp_eoma": 0, "nacks": 0},
            "sweeps": 0,
            "sweeps_logged": "first and changes only",
            "card_used_pct": card_pct,
        }
        return Record("session_end", "info", None, None, fields)

    def _close_session(self, reason: str) -> None:
        assert self.eventlog is not None
        self._log(self._session_end(reason))
        self.eventlog.sync_now()
        self.eventlog.close()
        self._prev_hash = self.eventlog.last_hash
        self._write_state(self._session)
        self.diag.log("info", "session", f"session {self._session} ended ({reason})")
        self.diag.flush()
        self.eventlog = None
        self.detect = None

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
