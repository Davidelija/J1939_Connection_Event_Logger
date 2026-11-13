"""decode: raw CAN frames to J1939 messages (docs/modules.md section 4, contract v1).

Layer 2: pure. No I/O, no clock, no threads. Time comes only from each
frame's ``ts_mono``.

``decode(frames, state, logger_sa=None) -> (msgs, stats, tx, state)``

* 29-bit data frames become ``J1939Msg``s (ID split into priority, PGN, SA,
  DA; PDU1 vs PDU2). 11-bit, remote and error frames are counted by type in
  ``DecodeStats.non_j1939`` and never decoded as J1939 (DET-19).
* Transport protocol (J1939-21): BAM and RTS/CTS transfers are reassembled,
  up to 1785 bytes, with at most ``limits.tp_sessions`` open at once. A
  transfer closes with a reason counted in ``DecodeStats.tp_closed``:
  ``completed``, ``aborted``, ``replaced``, ``oversize``, ``too_many_sessions``,
  ``duplicate``, ``bad_sequence``, ``timeout_t1`` to ``timeout_t4``. A
  rejected transfer addressed to the logger produces a Connection Abort
  ``TxRequest``. TP.CM and TP.DT frames themselves are not returned as
  messages; the reassembled message is, at the position of its last packet,
  with the time of its RTS or BAM.
* Extended transport protocol (ETP, PGNs 51200 and 50944) is recognized, not
  reassembled (DET-10): its frames are returned as ordinary messages and each
  ETP.CM RTS counts in ``etp_seen``.
* Malformed input is counted in ``DecodeStats.malformed`` by reason and never
  raises (SC-12a).
* Timeouts are checked against each frame's ``ts_mono``, so a transfer left
  open with no later traffic closes when the next frame arrives.

``DecodeStats`` is cumulative over the session (the counts since
``new_state``). ``DecodeState`` is opaque: callers pass it back unchanged
(DC-8).
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Optional

from j1939logger.types import Frame, J1939Msg, Name, TxRequest

__all__ = ["decode", "new_state", "decode_name", "split_id", "DecodeStats", "DecodeState"]

PGN_TP_CM = 60416
PGN_TP_DT = 60160
PGN_ETP_CM = 51200
PGN_ETP_DT = 50944
PGN_ADDRESS_CLAIM = 60928
PGN_REQUEST = 59904

TP_MAX_BYTES = 1785
GLOBAL = 255

# TP.CM control bytes (J1939-21)
_RTS, _CTS, _EOMA, _BAM, _ABORT = 16, 17, 19, 32, 255

# Connection Abort reasons (J1939-21)
ABORT_RESOURCES = 2
ABORT_TIMEOUT = 3
ABORT_BAD_SEQUENCE = 7
ABORT_DUPLICATE = 8
ABORT_OVERSIZE = 9

# Timeouts in seconds (J1939-21; docs/errors.md tp_error row)
T1, T2, T3, T4 = 0.75, 1.25, 1.25, 1.05


@dataclass
class DecodeStats:
    """Counts since the session started (DC-8)."""

    non_j1939: dict[str, int] = field(
        default_factory=lambda: {"standard": 0, "remote": 0, "error": 0}
    )
    tp_closed: dict[str, int] = field(default_factory=dict)
    malformed: dict[str, int] = field(default_factory=dict)
    etp_seen: int = 0


@dataclass
class _Transfer:
    sa: int
    da: int  # 255 for BAM
    pgn: int
    size: int
    packets: int
    priority: int
    ts_mono: float
    ts_kernel: float
    own: bool
    deadline: float
    timer: str  # which timeout applies next: "t1" to "t4"
    next_seq: int = 1
    window_end: int = 0  # last sequence number the current CTS allows (RTS/CTS only)
    data: bytearray = field(default_factory=bytearray)


@dataclass
class DecodeState:
    """Opaque decode state; only decode reads or changes it (DC-8)."""

    tp_sessions: int
    transfers: dict[tuple[int, int], _Transfer] = field(default_factory=dict)
    stats: DecodeStats = field(default_factory=DecodeStats)


def new_state(tp_sessions: int) -> DecodeState:
    """A fresh state; ``tp_sessions`` is ``limits.tp_sessions`` from the config."""
    if tp_sessions < 1:
        raise ValueError("limits.tp_sessions must be at least 1")
    return DecodeState(tp_sessions=tp_sessions)


def split_id(can_id: int) -> tuple[int, int, int, int]:
    """(priority, pgn, sa, da) from a 29-bit identifier; da is 255 for PDU2."""
    priority = (can_id >> 26) & 0x7
    edp_dp = (can_id >> 24) & 0x3
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    sa = can_id & 0xFF
    if pf < 240:  # PDU1: PS is the destination address
        return priority, (edp_dp << 16) | (pf << 8), sa, ps
    return priority, (edp_dp << 16) | (pf << 8) | ps, sa, GLOBAL


def decode_name(value: int) -> Name:
    """Decode a 64-bit NAME into its fields as raw numbers (IDN-1)."""
    return Name(
        value=value,
        aac=(value >> 63) & 0x1,
        industry_group=(value >> 60) & 0x7,
        vs_instance=(value >> 56) & 0xF,
        vehicle_system=(value >> 49) & 0x7F,
        function=(value >> 40) & 0xFF,
        function_instance=(value >> 35) & 0x1F,
        ecu_instance=(value >> 32) & 0x7,
        mfr_code=(value >> 21) & 0x7FF,
        identity=value & 0x1FFFFF,
    )


def _count(d: dict[str, int], key: str) -> None:
    d[key] = d.get(key, 0) + 1


def _pgn3(b: bytes) -> int:
    return b[0] | (b[1] << 8) | (b[2] << 16)


def _abort(sa: int, pgn: int, reason: int) -> TxRequest:
    # Connection Abort from the logger to the sender ``sa``.
    return TxRequest(
        pgn=PGN_TP_CM,
        da=sa,
        data=bytes([_ABORT, reason, 0xFF, 0xFF, 0xFF]) + pgn.to_bytes(3, "little"),
        kind="protocol",
    )


class _Run:
    def __init__(self, state: DecodeState, logger_sa: Optional[int]) -> None:
        self.state = state
        self.stats = state.stats
        self.logger_sa = logger_sa
        self.msgs: list[J1939Msg] = []
        self.tx: list[TxRequest] = []

    def close(self, key: tuple[int, int], reason: str) -> None:
        if self.state.transfers.pop(key, None) is not None:
            _count(self.stats.tp_closed, reason)

    def reject(self, sa: int, da: int, pgn: int, reason: str, abort_reason: int) -> None:
        _count(self.stats.tp_closed, reason)
        if self.logger_sa is not None and da == self.logger_sa:
            self.tx.append(_abort(sa, pgn, abort_reason))

    def expire(self, now: float) -> None:
        for key, t in list(self.state.transfers.items()):
            if now > t.deadline:
                self.close(key, "timeout_" + t.timer)
                if t.da != GLOBAL and self.logger_sa is not None and t.da == self.logger_sa:
                    self.tx.append(_abort(t.sa, t.pgn, ABORT_TIMEOUT))

    def frame(self, f: Frame) -> None:
        if f.error:
            _count(self.stats.non_j1939, "error")
            return
        if f.remote:
            _count(self.stats.non_j1939, "remote")
            return
        if not f.extended:
            _count(self.stats.non_j1939, "standard")
            return
        if len(f.data) > 8:
            _count(self.stats.malformed, "dlc")
            return
        self.expire(f.ts_mono)
        priority, pgn, sa, da = split_id(f.can_id)
        if pgn >> 16 == 0x3:  # EDP=1 and DP=1: ISO 15765-3, not J1939
            _count(self.stats.malformed, "reserved_edp_dp")
            return
        if pgn == PGN_TP_CM:
            self.tp_cm(f, priority, sa, da)
            return
        if pgn == PGN_TP_DT:
            self.tp_dt(f, sa, da)
            return
        if pgn == PGN_ETP_CM and len(f.data) >= 1 and f.data[0] == 20:  # ETP.CM RTS
            self.stats.etp_seen += 1
        if pgn == PGN_ADDRESS_CLAIM and len(f.data) != 8:
            _count(self.stats.malformed, "claim_length")
            return
        if pgn == PGN_REQUEST and len(f.data) not in (3, 8):
            _count(self.stats.malformed, "request_length")
            return
        self.emit(f, priority, pgn, sa, da, bytes(f.data), via_tp=False)

    def emit(
        self, f: Frame, priority: int, pgn: int, sa: int, da: int, data: bytes, via_tp: bool
    ) -> None:
        self.msgs.append(
            J1939Msg(
                ts_mono=f.ts_mono,
                ts_kernel=f.ts_kernel,
                priority=priority,
                pgn=pgn,
                sa=sa,
                da=da,
                data=data,
                via_tp=via_tp,
                own=f.own,
                reply_to_logger=self.logger_sa is not None and da == self.logger_sa,
            )
        )

    def tp_cm(self, f: Frame, priority: int, sa: int, da: int) -> None:
        d = f.data
        if len(d) != 8:
            _count(self.stats.malformed, "tp_cm_length")
            return
        control = d[0]
        if control in (_RTS, _BAM):
            self.open(f, priority, sa, GLOBAL if control == _BAM else da, d)
        elif control == _CTS:
            # From the receiver (sa) to the sender (da).
            t = self.state.transfers.get((da, sa))
            if t is None:
                return
            count, next_seq = d[1], d[2]
            if count == 0:
                t.deadline, t.timer = f.ts_mono + T4, "t4"
            else:
                t.window_end = next_seq + count - 1
                t.deadline, t.timer = f.ts_mono + T2, "t2"
        elif control == _EOMA:
            pass  # the transfer completed at its last packet
        elif control == _ABORT:
            for key in ((sa, da), (da, sa)):
                self.close(key, "aborted")
        else:
            _count(self.stats.malformed, "tp_cm_control")

    def open(self, f: Frame, priority: int, sa: int, da: int, d: bytes) -> None:
        size = d[1] | (d[2] << 8)
        packets = d[3]
        pgn = _pgn3(d[5:8])
        bam = da == GLOBAL
        if size > TP_MAX_BYTES:
            self.reject(sa, da, pgn, "oversize", ABORT_OVERSIZE)
            return
        if size < 9 or packets != (size + 6) // 7:
            _count(self.stats.malformed, "tp_size")
            return
        key = (sa, da)
        if key in self.state.transfers:
            self.close(key, "replaced")
        if len(self.state.transfers) >= self.state.tp_sessions:
            self.reject(sa, da, pgn, "too_many_sessions", ABORT_RESOURCES)
            return
        self.state.transfers[key] = _Transfer(
            sa=sa,
            da=da,
            pgn=pgn,
            size=size,
            packets=packets,
            priority=priority,
            ts_mono=f.ts_mono,
            ts_kernel=f.ts_kernel,
            own=f.own,
            deadline=f.ts_mono + (T1 if bam else T3),
            timer="t1" if bam else "t3",
            window_end=packets if bam else 0,
        )

    def tp_dt(self, f: Frame, sa: int, da: int) -> None:
        d = f.data
        if len(d) != 8:
            _count(self.stats.malformed, "tp_dt_length")
            return
        key = (sa, da)
        t = self.state.transfers.get(key)
        if t is None:
            _count(self.stats.malformed, "tp_dt_no_session")
            return
        seq = d[0]
        if seq < t.next_seq:
            self.close(key, "duplicate")
            if t.da != GLOBAL and t.da == self.logger_sa:
                self.tx.append(_abort(t.sa, t.pgn, ABORT_DUPLICATE))
            return
        if seq > t.next_seq or seq > t.packets:
            self.close(key, "bad_sequence")
            if t.da != GLOBAL and t.da == self.logger_sa:
                self.tx.append(_abort(t.sa, t.pgn, ABORT_BAD_SEQUENCE))
            return
        t.data += d[1:8]
        t.next_seq += 1
        if seq == t.packets:
            self.state.transfers.pop(key)
            _count(self.stats.tp_closed, "completed")
            first = Frame(
                ts_kernel=t.ts_kernel,
                ts_mono=t.ts_mono,
                can_id=0,
                extended=True,
                remote=False,
                error=False,
                data=b"",
                own=t.own,
            )
            self.emit(first, t.priority, t.pgn, t.sa, t.da, bytes(t.data[: t.size]), via_tp=True)
            return
        if t.da != GLOBAL and seq >= t.window_end:
            t.deadline, t.timer = f.ts_mono + T3, "t3"  # waiting for the next CTS
        else:
            t.deadline, t.timer = f.ts_mono + T1, "t1"


def decode(
    frames: Sequence[Frame], state: DecodeState, logger_sa: Optional[int] = None
) -> tuple[list[J1939Msg], DecodeStats, list[TxRequest], DecodeState]:
    """Decode a batch of frames. Never raises on frame content (SC-12a).

    ``logger_sa`` is the logger's current address, or None before it has one;
    it marks replies to the logger and decides when a rejected transfer gets a
    Connection Abort. The returned stats are a copy of the session totals.
    """
    run = _Run(state, logger_sa)
    for f in frames:
        run.frame(f)
    return run.msgs, copy.deepcopy(state.stats), run.tx, state
