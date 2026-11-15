"""CAN interface retry, the bit rate, transmitting and the NP-18 guard.

Part of ``Session`` (docs/modules.md section 4); split from session.py with no change
in behaviour.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Iterable
from typing import Any, Callable, Optional

from j1939logger.admin import RESTART_EXIT
from j1939logger.config import (
    LibraryError,
    validate_library,
)
from j1939logger.requests import PGN_VIN, RequestOutcome
from j1939logger.session.files import (
    BITRATES,
    CAN_LOST,
    CAN_RETRY_FIRST_S,
    CAN_RETRY_MAX_S,
    _vin_text,
)
from j1939logger.session.state import _State
from j1939logger.types import Frame, PlatformError, Record, TxRequest


class _CanPart(_State):
    def _kernel_drops(self) -> None:
        """A notice fault the first time the kernel drops frames in a session (rx_overflow)."""
        if self.eventlog is None or self._drops_reported:
            return
        drops = self.capture.stats().kernel_drops
        if drops > 0:
            self._drops_reported = True  # once per session; the count is in session_end
            self._log(Record("fault", "notice", None, None, {
                "cause": f"the kernel dropped {drops} received frames (SO_RXQ_OVFL)",
                "logger_action": "continued; the total is in session_end",
            }))  # fmt: skip

    def _can_lost(self, exc: PlatformError) -> None:
        now = self.clock.mono()
        if self._can_down_since is None:
            self._can_down_since, self._can_tries = now, 0
            self._can_kind = exc.kind
            self.diag.log("error", "capture", f"CAN interface {exc.kind}: {exc}")
        self._can_tries += 1
        delay = min(CAN_RETRY_MAX_S, CAN_RETRY_FIRST_S * 2 ** (self._can_tries - 1))
        self._can_retry_at = now + delay

    def _retry_can(self) -> None:
        """Try to reopen the CAN socket when the backoff has passed; one fault with a count."""
        if self._can_down_since is None:
            return
        now = self.clock.mono()
        waited = now - self._can_down_since
        if not self._can_fault_written and waited >= float(self._get("can.bitrate_fault_s", 60)):
            self._can_fault_written = True
            self._can_fault(waited)
        if now < self._can_retry_at:
            return
        try:
            self.capture.stop()
            self.capture.start(listen_only=self._bitrate is None or self._guard_holds)
        except PlatformError as exc:
            if exc.kind not in CAN_LOST:
                raise
            self._can_lost(exc)
            return
        self.diag.log("info", "capture", f"CAN interface back after {waited:.0f} s, "
                                         f"{self._can_tries} tries")  # fmt: skip
        self._can_down_since = None
        self._can_fault_written = False

    def _can_fault(self, waited: float) -> None:
        cause = (f"CAN interface {'missing' if self._can_kind == 'can_missing' else 'down'} "
                 f"for {waited:.0f} s ({self._can_tries} tries)")  # fmt: skip
        action = "retrying with backoff; recording resumes when it returns"
        if self.eventlog is not None:
            self._log(
                Record("fault", "high", None, None, {"cause": cause, "logger_action": action})
            )
        else:
            self._startup_faults.append((cause, action))  # written in the next session

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
        self._retry_can()
        frames: list[Frame] = []
        if self._can_down_since is None:
            try:
                frames = self.capture.read_batch(max_n)
            except PlatformError as exc:
                if exc.kind not in CAN_LOST:
                    raise
                self._can_lost(exc)  # keep the session; retry the socket (errors.md can_down)
        self._kernel_drops()
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
        self._run_commands()
        self._timers()
        self._drain_faults()
        return len(frames)

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
            assert self.requests is not None
            tx, address, requests = self.transmit, self.address, self.requests
            self._tx_call("transmit.enable", lambda: tx.enable(self.capture.transmit_handle()))
            sends = self._tx_call("address.start", address.start)
            self._submit(sends or [])
            self._claim_sent_mono = self.clock.mono()
            self._tx_call("requests.session_start", requests.session_start)
            self._tx_call("transmit.pump", tx.pump)
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

    def _tx_call(self, where: str, fn: Callable[[], Any]) -> Any:
        """Run one call into ``address``, ``requests`` or ``transmit`` (NP-18).

        Any unexpected error turns transmit off for the session with a high fault
        (``transmit.disable``), puts the traceback in the diagnostic log, and stops
        further calls into those modules; receiving, detection and logging go on.
        """
        if self._tx_failed:
            return None
        try:
            return fn()
        except Exception as exc:  # NP-18: "any unexpected error" in the transmit or request code
            self._tx_failed = True
            self.diag.log(
                "error", "session", f"{where}: " + traceback.format_exc().replace("\n", " | ")
            )
            self._transmit_off(f"unexpected error: {type(exc).__name__} in {where}")
            return None

    def _transmit_off(self, reason: str) -> None:
        """Turn transmit off for the session, even if ``transmit.disable`` itself fails (NP-18).

        ``transmit.disable`` writes the high fault. If it raises, or there is no
        ``transmit``, the session writes the fault itself, keeps its own off reason
        and makes no more calls into ``address``, ``requests`` or ``transmit``;
        nothing escapes, and receiving, detection and logging go on.
        """
        if self.transmit is not None:
            try:
                self.transmit.disable(reason)
                return
            except Exception:  # NP-18: an error while turning transmit off
                self.diag.log(
                    "error", "session",
                    "transmit.disable: " + traceback.format_exc().replace("\n", " | "),
                )  # fmt: skip
        self._tx_failed = True
        self._tx_off_reason = reason
        self._log(Record("fault", "high", None, None, {
            "cause": f"transmit turned off: {reason}",
            "logger_action": "listen-only for the rest of the session",
        }))  # fmt: skip

    def _transmit_off_reason(self) -> Optional[str]:
        """Why transmit is off this session, or None while it may still send."""
        if self._tx_off_reason is not None:
            return self._tx_off_reason
        return self.transmit.off_reason if self.transmit is not None else None

    def _submit(self, sends: Iterable[tuple[TxRequest, int]]) -> None:
        if self.transmit is None:
            return
        tx = self.transmit

        def send_all() -> None:
            for req, sa in sends:
                tx.submit(req, sa)
            if self.address is not None:
                tx.set_source(self.address.current)

        self._tx_call("transmit.submit", send_all)

    def _run_requests(self) -> None:
        if self.transmit is None or self.requests is None or not self.transmit.enabled:
            return
        tx, requests = self.transmit, self.requests

        def run() -> None:
            if self.logger_sa is not None:
                for req in requests.poll():
                    tx.submit(req, self.logger_sa)
            tx.pump()

        self._tx_call("requests.poll", run)

    def _collect(self) -> None:
        """Records and outcomes from address, requests and transmit."""
        if self.requests is not None:
            requests = self.requests
            for record in self._tx_call("requests.take_records", requests.take_records) or []:
                self._log(record)
            for outcome in self._tx_call("requests.take_outcomes", requests.take_outcomes) or []:
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
