"""transmit: the only path to the bus (docs/modules.md section 4, contract v1, frozen for step 3).

Layer 1. Safety-critical (CLAUDE.md rule 4; review by Vaughan Lynn or Elijah
Umaru on every change). Every frame the logger sends passes through
``submit()`` and is sent by ``pump()`` on capture's send handle (DC-12).

Guard (NP-9, NP-18, DC-12). A request is refused and transmit turns off for
the rest of the session, with a high ``fault`` record (``tx_breach``), when:

* its PGN is not in ``transmit.allow_list`` (narrowed to this release's list);
* it is a Request (59904) for a PGN not in ``requests.allow_list``;
* it is an Address Claim (60928) with any NAME but the logger's;
* it is an Acknowledgment (59392) that is not a NACK (control byte 1);
* it is a TP.CM (60416) that is not CTS, EOMA or Abort (the logger never
  sends RTS or BAM: it provides no data);
* its ``kind`` does not match its PGN (``request`` only for 59904, ``protocol``
  for the rest), or it uses the null address (254) for anything but a claim.

The offending frame is never sent. Transmit never turns back on in the same
session (rule 4); ``enable()`` after ``disable()`` is refused.

Limits (NP-16, NP-6, DC-12):

* at most ``transmit.max_frames_per_s`` frames in any sliding 1 s window,
  every frame counted; a frame over the cap waits in the queue;
* protocol frames go ahead of queued requests;
* at most ``transmit.max_outstanding_per_dest`` requests outstanding per
  destination (global requests count as destination 255); ``requests`` calls
  ``release(da)`` on a reply, NACK or timeout;
* after an Address Claim, nothing but claims is sent for
  ``address.claim_wait_ms`` (NP-6).

Nothing is sent before ``enable()``, which ``session`` calls only after the
bit rate is confirmed and when the restart guard does not hold (NP-1, NP-17,
NP-19). A send error (``ENOBUFS`` or any other) turns transmit off (NP-18);
``disable(reason)`` also does, on bus-off or error-passive (NP-3).
"""

from __future__ import annotations

import errno
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from j1939logger.clock import Clock
from j1939logger.platform.interface import Platform
from j1939logger.types import PlatformError, Record, TxRequest

__all__ = [
    "Transmit",
    "TxResult",
    "SendHandle",
    "RELEASE_TRANSMIT_ALLOW",
    "RELEASE_REQUEST_ALLOW",
    "PGN_REQUEST",
    "PGN_CLAIM",
    "PGN_ACK",
    "PGN_TP_CM",
    "can_id",
]

# The allow-lists this release may use (NP-9). Configuration can narrow them,
# never widen them; widening needs a software release (CLAUDE.md rule 4).
RELEASE_TRANSMIT_ALLOW = frozenset({59904, 60928, 59392, 60416})
RELEASE_REQUEST_ALLOW = frozenset({60928, 65254, 65260, 65259, 65242, 64965})

PGN_REQUEST = 59904
PGN_CLAIM = 60928
PGN_ACK = 59392
PGN_TP_CM = 60416
NULL_SA = 254
GLOBAL = 255
_TP_CM_ALLOWED = {17: "tp_cts", 19: "tp_eoma", 255: "tp_aborts"}
_NACK = 1


class SendHandle(Protocol):
    """Capture's send handle (DC-12): sends one frame on capture's socket."""

    def send(self, can_id: int, data: bytes) -> None: ...


@dataclass(frozen=True)
class TxResult:
    accepted: bool  # queued for sending
    reason: Optional[str] = None  # why it was refused


@dataclass
class _Queued:
    req: TxRequest
    sa: int


@dataclass
class _Counts:
    claims: int = 0
    requests: int = 0
    tp_cts: int = 0
    tp_eoma: int = 0
    nacks: int = 0
    tp_aborts: int = 0
    refused: int = 0
    by_pgn: dict[int, int] = field(default_factory=dict)


def can_id(pgn: int, sa: int, da: int, priority: int) -> int:
    """29-bit identifier for a J1939 frame."""
    pf = (pgn >> 8) & 0xFF
    ps = da if pf < 240 else pgn & 0xFF
    return (priority << 26) | (((pgn >> 16) & 0x3) << 24) | (pf << 16) | (ps << 8) | sa


class Transmit:
    def __init__(
        self,
        platform: Platform,
        clock: Clock,
        settings: Mapping[str, Any],
        logger_name: int,
    ) -> None:
        self._platform = platform
        self._clock = clock
        # Configuration can narrow the allow-lists, never widen them (rule 4).
        self._allow = frozenset(settings["transmit.allow_list"]) & RELEASE_TRANSMIT_ALLOW
        self._request_allow = frozenset(settings["requests.allow_list"]) & RELEASE_REQUEST_ALLOW
        self._max_fps = int(settings["transmit.max_frames_per_s"])
        self._max_out = int(settings["transmit.max_outstanding_per_dest"])
        self._claim_wait_s = float(settings.get("address.claim_wait_ms", 250)) / 1000.0
        self._name_bytes = logger_name.to_bytes(8, "little")
        self._handle: Optional[SendHandle] = None
        self._enabled = False
        self._off_reason: Optional[str] = None
        self._protocol: deque[_Queued] = deque()
        self._requests: deque[_Queued] = deque()
        self._sent: deque[float] = deque()
        self._outstanding: dict[int, int] = {}
        self._claim_hold_until = 0.0
        self._sa: Optional[int] = None
        self.counts = _Counts()
        self._faults: list[Record] = []

    # -- state ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def off_reason(self) -> Optional[str]:
        return self._off_reason

    def enable(self, handle: SendHandle) -> bool:
        """Allow sending (bit rate confirmed, restart guard clear). Never after ``disable``."""
        if self._off_reason is not None:
            return False
        self._handle = handle
        self._enabled = True
        return True

    def disable(self, reason: str) -> None:
        """Turn transmit off for the rest of the session; queued frames are dropped."""
        if self._off_reason is not None:
            return
        self._enabled = False
        self._off_reason = reason
        self._protocol.clear()
        self._requests.clear()
        self._faults.append(
            Record(
                type="fault",
                sev="high",
                utc=self._clock.to_utc(self._clock.mono()),
                veh_time=None,
                fields={
                    "cause": f"transmit turned off: {reason}",
                    "logger_action": "listen-only for the rest of the session",
                },
            )
        )

    def set_source(self, sa: Optional[int]) -> None:
        """The logger's current address (from ``address``), or None before a claim."""
        self._sa = sa

    def take_faults(self) -> list[Record]:
        out, self._faults = self._faults, []
        return out

    # -- the guard --------------------------------------------------------------

    def _breach(self, req: TxRequest, sa: int) -> Optional[str]:
        if req.kind not in ("protocol", "request"):
            return f"unknown kind {req.kind!r}"
        if req.pgn not in self._allow:
            return f"PGN {req.pgn} is not in the transmit allow-list"
        if not 0 <= req.da <= 255 or not 0 <= sa <= NULL_SA:
            return "address out of range"
        if req.pgn == PGN_REQUEST:
            if req.kind != "request":
                return "a Request must have kind 'request'"
            if len(req.data) != 3:
                return "a Request carries exactly 3 bytes"
            wanted = req.data[0] | (req.data[1] << 8) | (req.data[2] << 16)
            if wanted not in self._request_allow:
                return f"Request for PGN {wanted} is not in the request allow-list"
        elif req.kind != "protocol":
            return f"PGN {req.pgn} must have kind 'protocol'"
        if req.pgn == PGN_CLAIM and bytes(req.data) != self._name_bytes:
            return "Address Claim with a NAME other than the logger's"
        if req.pgn == PGN_ACK and (len(req.data) != 8 or req.data[0] != _NACK):
            return "Acknowledgment that is not a NACK"
        if req.pgn == PGN_TP_CM and (len(req.data) != 8 or req.data[0] not in _TP_CM_ALLOWED):
            return "TP.CM that is not CTS, EOMA or Abort"
        if sa == NULL_SA and req.pgn != PGN_CLAIM:
            return "only Cannot Claim may use the null address"
        if len(req.data) > 8:
            return "more than 8 data bytes"
        return None

    # -- queueing -----------------------------------------------------------------

    def submit(self, req: TxRequest, sa: Optional[int] = None) -> TxResult:
        """Check a request and queue it. A breach turns transmit off (NP-18)."""
        source = self._sa if sa is None else sa
        if self._off_reason is not None:
            self.counts.refused += 1
            return TxResult(False, "transmit is off for this session")
        if not self._enabled:
            self.counts.refused += 1
            return TxResult(False, "transmit is not enabled (bit rate not confirmed)")
        if source is None:
            self.counts.refused += 1
            return TxResult(False, "the logger has no address")
        reason = self._breach(req, source)
        if reason is not None:
            self.counts.refused += 1
            self.disable(f"tx_breach: {reason}")
            return TxResult(False, reason)
        queue = self._requests if req.kind == "request" else self._protocol
        queue.append(_Queued(req, source))
        return TxResult(True)

    def release(self, da: int) -> None:
        """A request to ``da`` got a reply, a NACK or timed out (called by ``requests``)."""
        if self._outstanding.get(da, 0) > 0:
            self._outstanding[da] -= 1

    def pending(self) -> int:
        return len(self._protocol) + len(self._requests)

    def pump(self) -> int:
        """Send what the limits allow now; returns the number of frames sent."""
        sent = 0
        while self._enabled and self._handle is not None:
            now = self._clock.mono()
            while self._sent and now - self._sent[0] >= 1.0:
                self._sent.popleft()
            if len(self._sent) >= self._max_fps:
                break  # NP-16: wait for the 1 s window
            item = self._next(now)
            if item is None:
                break
            if not self._send(item, now):
                break
            sent += 1
        return sent

    def _next(self, now: float) -> Optional[_Queued]:
        holding = now < self._claim_hold_until  # NP-6
        for i, item in enumerate(self._protocol):
            if holding and item.req.pgn != PGN_CLAIM:
                continue
            del self._protocol[i]
            return item
        if holding:
            return None
        for i, item in enumerate(self._requests):
            if self._outstanding.get(item.req.da, 0) >= self._max_out:
                continue  # NP-16: one outstanding request per destination
            del self._requests[i]
            return item
        return None

    def _send(self, item: _Queued, now: float) -> bool:
        req = item.req
        priority = 7 if req.pgn == PGN_TP_CM else 6
        assert self._handle is not None
        try:
            self._platform.fault("can_send")
            self._handle.send(can_id(req.pgn, item.sa, req.da, priority), bytes(req.data))
        except PlatformError as exc:
            self.disable(f"{exc.kind} on send")
            return False
        except OSError as exc:
            name = (
                "enobufs"
                if exc.errno == errno.ENOBUFS
                else (errno.errorcode.get(exc.errno or 0) or "send error")
            )
            self.disable(f"{name} on send")
            return False
        self._sent.append(now)
        self.counts.by_pgn[req.pgn] = self.counts.by_pgn.get(req.pgn, 0) + 1
        if req.pgn == PGN_CLAIM:
            self.counts.claims += 1
            self._claim_hold_until = now + self._claim_wait_s
        elif req.pgn == PGN_REQUEST:
            self.counts.requests += 1
            self._outstanding[req.da] = self._outstanding.get(req.da, 0) + 1
        elif req.pgn == PGN_ACK:
            self.counts.nacks += 1
        elif req.pgn == PGN_TP_CM:
            key = _TP_CM_ALLOWED[req.data[0]]
            setattr(self.counts, key, getattr(self.counts, key) + 1)
        return True

    def logger_tx(self) -> dict[str, int]:
        """Counts for ``session_end.logger_tx``."""
        c = self.counts
        return {
            "claims": c.claims,
            "requests": c.requests,
            "tp_cts": c.tp_cts,
            "tp_eoma": c.tp_eoma,
            "nacks": c.nacks,
        }
