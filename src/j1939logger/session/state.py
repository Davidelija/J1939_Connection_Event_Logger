"""The session's state (``__init__``) and declarations shared by its parts.

Part of ``Session`` (docs/modules.md section 4); split from session.py with no change
in behaviour.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterable, Mapping
from typing import Any, Callable, Optional, Union

from j1939logger.address import Address
from j1939logger.admin import DiagLog
from j1939logger.capture import Capture
from j1939logger.clock import Clock
from j1939logger.config import (
    Inventory,
    Library,
)
from j1939logger.decode import new_state
from j1939logger.detect import Detect
from j1939logger.eventlog import ZERO_HASH, EventLog
from j1939logger.inventory import (
    Training,
)
from j1939logger.monitor import Monitor
from j1939logger.platform.interface import Platform
from j1939logger.rawcap import RawCap
from j1939logger.requests import RequestOutcome, Requests
from j1939logger.retention import Retention
from j1939logger.session.files import (
    APPROVED,
    _Ident,
)
from j1939logger.status import State, Status
from j1939logger.store import Store
from j1939logger.transmit import Transmit
from j1939logger.types import Frame, Name, PlatformError, Record, TxRequest


class _State:
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
        # A cause, or (cause, logger action); a bare cause is written as "running untrained".
        self._startup_faults: list[Union[str, tuple[str, str]]] = list(startup_faults or [])
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
        self._tx_failed = False  # an unexpected error in the transmit or request code (NP-18)
        # Why transmit is off when transmit.disable itself failed (NP-18); else None.
        self._tx_off_reason: Optional[str] = None
        self._can_down_since: Optional[float] = None
        self._can_retry_at = 0.0
        self._can_tries = 0
        self._can_kind = "can_missing"
        self._can_fault_written = False
        self._drops_reported = False
        self.status = Status(platform, settings)
        self._unreviewed: list[str] = []  # high events not yet cleared (STS-2, DC-21)
        self._retrieved: list[str] = []  # files the laptop has retrieved (LOG-11)
        self._inventory_active = True  # False after retrain until a training is confirmed
        self._high_fault: Optional[str] = None
        self._card_fault: Optional[str] = None  # card not writable at start-up (STS-19)
        self._vin_status: Optional[str] = None
        self._status_mono = float("-inf")
        self.exit_code = 0
        # Laptop commands from cmdserver, handled one at a time in the main loop (STS-23).
        self.commands: queue.SimpleQueue[Any] = queue.SimpleQueue()
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

    # -- declared here, defined in another part --------------------------------------

    def _transmit_off(self, reason: str) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _transmit_off_reason(self) -> Optional[str]:
        raise NotImplementedError  # defined in another part of Session

    def _get(self, key: str, default: Any) -> Any:
        raise NotImplementedError  # defined in another part of Session

    def _can_lost(self, exc: PlatformError) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _load_library(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def stop(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    @property
    def logger_sa(self) -> Optional[int]:
        raise NotImplementedError  # defined in another part of Session

    def _try_bitrate(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _tx_call(self, where: str, fn: Callable[[], Any]) -> Any:
        raise NotImplementedError  # defined in another part of Session

    def _submit(self, sends: Iterable[tuple[TxRequest, int]]) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _collect(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _process(self, frames: list[Frame]) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _log_detection(self, record: Record, ts_mono: Optional[float] = None) -> None:
        raise NotImplementedError  # defined in another part of Session

    @property
    def _untrained(self) -> bool:
        raise NotImplementedError  # defined in another part of Session

    def _newest(self, kind: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError  # defined in another part of Session

    def _reload_from_card(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def status_state(self) -> State:
        raise NotImplementedError  # defined in another part of Session

    def _card_check(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _update_status(self, force: bool = False) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _run_commands(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _raw_start(self, conn: int, ts_mono: float) -> Optional[str]:
        raise NotImplementedError  # defined in another part of Session

    def _raw_poll(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _retention(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _vin_mismatch(self, check: Record) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _drop_inventory(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _now_text(self) -> Optional[str]:
        raise NotImplementedError  # defined in another part of Session

    def _classify(
        self, name: Optional[Name], since_s: float, what: str
    ) -> tuple[str, str, str, str]:
        raise NotImplementedError  # defined in another part of Session

    def _end_summary(self, conn: int) -> Mapping[str, Any]:
        raise NotImplementedError  # defined in another part of Session

    def _identity_outcome(self, outcome: RequestOutcome) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _final_identification(self, record: Record) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _detection(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _end_connections(self, reason: str) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _timers(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _log(self, record: Record, ts_mono: Optional[float] = None) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _drain_faults(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _reset_counts(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _write_state(self, session: int) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _save_state(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _open_session(self, wake: str) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _settle_header(self) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _close_session(self, reason: str) -> None:
        raise NotImplementedError  # defined in another part of Session

    def _roll_over(self) -> None:
        raise NotImplementedError  # defined in another part of Session
