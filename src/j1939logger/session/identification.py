"""Identification in the session (step 5, DC-17).

Part of ``Session`` (docs/modules.md section 4); split from session.py with no change
in behaviour.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from j1939logger.identify import (
    Identification,
    classify,
    identification_fields,
    identification_record,
    identify,
    reclassify,
)
from j1939logger.requests import RequestOutcome
from j1939logger.session.files import (
    IDENTITY_REQUESTS,
    _Ident,
)
from j1939logger.session.state import _State
from j1939logger.types import Name, Record


class _IdentificationPart(_State):
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
        if self._transmit_off_reason() is not None:
            return True  # bus-off, error-passive, a breach or an unexpected error (NP-3, NP-18)
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
