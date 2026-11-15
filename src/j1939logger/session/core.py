"""The ``Session`` class: lifecycle, frames, records, opening and closing.

The other parts are
mixed in from can, card, commands and identification; the shared state is in state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from j1939logger.address import Address
from j1939logger.decode import bus_state, decode, new_state
from j1939logger.detect import Detect
from j1939logger.eventlog import ZERO_HASH, EventLog, format_utc, scan_tail
from j1939logger.monitor import Monitor
from j1939logger.rawcap import RawCap
from j1939logger.requests import Requests
from j1939logger.retention import Retention
from j1939logger.session.can import _CanPart
from j1939logger.session.card import _CardPart
from j1939logger.session.commands import _CommandsPart
from j1939logger.session.files import (
    APPROVED,
    CAN_LOST,
    CONNECTION_END_REASON,
    LOG_FORMAT,
    STATE_FORMAT,
    SW_VERSION,
    _Ident,
    operator_key_fingerprints,
    session_files,
)
from j1939logger.session.identification import _IdentificationPart
from j1939logger.transmit import Transmit
from j1939logger.types import Frame, J1939Msg, PlatformError, Record


class Session(_CanPart, _CardPart, _CommandsPart, _IdentificationPart):
    def _get(self, key: str, default: Any) -> Any:
        return self._settings.get(key, default)

    def start(self) -> None:
        """Power-on: load the device library, open capture listen-only and the first session.

        A missing CAN interface does not stop the logger: capture is retried with
        backoff and the first session opens on the first frame (errors.md can_missing).
        """
        self._load_library()
        try:
            self.capture.start(listen_only=True)
        except PlatformError as exc:
            if exc.kind not in CAN_LOST:
                raise
            self._can_lost(exc)
            return
        self._open_session(wake="power-on")

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
            address = self.address
            got = self._tx_call("address.on_message", lambda: address.on_message(msg))
            if got is not None:
                sends, records = got
                self._submit(sends)
                for record in records:
                    self._log(record, msg.ts_mono)
        if self.requests is not None:
            requests = self.requests
            self._tx_call("requests.on_message", lambda: requests.on_message(msg, self.logger_sa))
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
            requests, conn_id, sa = self.requests, record.conn, int(record.fields["sa"])
            self._tx_call("requests.identify", lambda: requests.identify(conn_id, sa, value))

    @property
    def _untrained(self) -> bool:
        """Untrained (TRN-9): no inventory, or dropped for this session (DET-14, training)."""
        return self._inventory is None or self._dropped

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
        self._tx_failed = False
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
        for item in self._startup_faults:
            message, action = item if isinstance(item, tuple) else (item, "running untrained")
            self._log(Record("fault", "high", None, None,
                             {"cause": message, "logger_action": action}))  # fmt: skip
        self._startup_faults = []
        self._drops_reported = False
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
        keys = operator_key_fingerprints(keys_dir)  # LAP-8
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
