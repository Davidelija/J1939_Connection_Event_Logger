"""address: the logger's own address claim (docs/modules.md section 4, v1, frozen for step 3).

Layer 3: no I/O; time only through ``clock``. It produces ``TxRequest``s with
the source address to send them from; ``session`` passes them to ``transmit``,
which checks them again (DC-12).

* Address choice (NP-4, DC-12): from ``address.claim_from`` down to
  ``address.claim_down_to``, skipping the inventory's addresses, addresses
  claimed so far this session and ``address.reserved``.
* The logger's NAME is arbitrary-address-capable, on-highway, with every other
  field at its maximum (NP-5), so it is higher than any vehicle NAME and loses
  every contest: a claim by another NAME for the logger's address takes it.
* On losing (NP-7): one more address; after ``address.claim_retries`` + 1
  losses, Cannot Claim (a claim from the null address, 254) and receive-only
  for the session. Each loss is an ``address_conflict`` record (DET-4).
* Requests addressed to the logger (NP-8): Request for Address Claim (global or
  to the logger) is answered with the claim, or with Cannot Claim once lost;
  any other request sent to the logger's address is NACKed; global requests
  for other PGNs get no answer. A Commanded Address (65240) directed at the
  logger's NAME is ignored: the logger never changes address on command.
* The 250 ms wait after a claim (NP-6) is enforced by ``transmit``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional

from j1939logger.clock import Clock
from j1939logger.types import J1939Msg, Record, TxRequest

__all__ = ["Address", "PGN_CLAIM", "PGN_REQUEST", "PGN_ACK", "PGN_COMMANDED_ADDRESS", "NULL_SA"]

PGN_CLAIM = 60928
PGN_REQUEST = 59904
PGN_ACK = 59392
PGN_COMMANDED_ADDRESS = 65240
NULL_SA = 254
GLOBAL = 255

Send = tuple[TxRequest, int]  # (request, source address)


class Address:
    def __init__(
        self,
        clock: Clock,
        settings: Mapping[str, Any],
        logger_name: int,
        inventory_addresses: Iterable[int] = (),
    ) -> None:
        self._clock = clock
        self._name = logger_name
        self._name_bytes = logger_name.to_bytes(8, "little")
        self._from = int(settings["address.claim_from"])
        self._down_to = int(settings["address.claim_down_to"])
        self._reserved = set(settings["address.reserved"])
        self._retries = int(settings["address.claim_retries"])
        self._skip = set(inventory_addresses)
        self._claimed_by_others: set[int] = set()
        self._tried: set[int] = set()
        self._losses = 0
        self.current: Optional[int] = None
        self.lost = False  # Cannot Claim sent: receive-only for the session

    # -- choosing and claiming -----------------------------------------------------

    def _candidate(self) -> Optional[int]:
        for sa in range(self._from, self._down_to - 1, -1):
            if sa in self._skip or sa in self._reserved or sa in self._claimed_by_others:
                continue
            if sa in self._tried:
                continue
            return sa
        return None

    def _claim(self, sa: int) -> Send:
        return (TxRequest(PGN_CLAIM, GLOBAL, self._name_bytes, "protocol"), sa)

    def start(self) -> list[Send]:
        """Claim the first free address (after the bit rate is confirmed)."""
        if self.lost or self.current is not None:
            return []
        return self._next_claim()

    def _next_claim(self) -> list[Send]:
        sa = self._candidate()
        if sa is None or self._losses > self._retries:
            return self._cannot_claim()
        self._tried.add(sa)
        self.current = sa
        return [self._claim(sa)]

    def _cannot_claim(self) -> list[Send]:
        self.current = None
        self.lost = True
        return [self._claim(NULL_SA)]

    # -- messages ------------------------------------------------------------------------

    def on_message(self, msg: J1939Msg) -> tuple[list[Send], list[Record]]:
        if msg.own:
            return [], []
        if msg.pgn == PGN_CLAIM and len(msg.data) == 8:
            return self._on_claim(msg)
        if msg.pgn == PGN_REQUEST and len(msg.data) >= 3:
            return self._on_request(msg), []
        # A Commanded Address (65240) to the logger's NAME is ignored (NP-8).
        return [], []

    def _on_claim(self, msg: J1939Msg) -> tuple[list[Send], list[Record]]:
        if msg.sa < NULL_SA:
            self._claimed_by_others.add(msg.sa)
        if self.current is None or msg.sa != self.current:
            return [], []
        # Another NAME claims the logger's address. The logger's NAME is the highest
        # possible, so it always concedes (NP-5, NP-7).
        other = int.from_bytes(msg.data, "little")
        lost_sa = self.current
        self._losses += 1
        sends = self._next_claim()
        action = (
            "Cannot Claim; receive-only for the session"
            if self.lost
            else f"conceded; claiming {self.current}"
        )
        record = Record(
            type="address_conflict",
            sev="notice",
            utc=self._clock.to_utc(msg.ts_mono),
            veh_time=None,
            fields={
                "sa": lost_sa,
                "names": [f"0x{self._name:016X}", f"0x{other:016X}"],
                "cause": "the logger lost its claim",
                "winner": f"0x{other:016X}",
                "logger_action": action,
            },
        )
        return sends, [record]

    def _on_request(self, msg: J1939Msg) -> list[Send]:
        wanted = msg.data[0] | (msg.data[1] << 8) | (msg.data[2] << 16)
        to_logger = self.current is not None and msg.da == self.current
        if wanted == PGN_CLAIM and (
            msg.da == GLOBAL or to_logger or (self.lost and msg.da == NULL_SA)
        ):
            if self.lost:
                return [self._claim(NULL_SA)]
            if self.current is not None:
                return [self._claim(self.current)]
            return []
        if to_logger:
            assert self.current is not None
            return [(self._nack(wanted, msg.sa), self.current)]
        return []

    @staticmethod
    def _nack(pgn: int, requester: int) -> TxRequest:
        # Acknowledgment, control byte 1 (NACK), to global with the requester's address (J1939-21).
        data = bytes([1, 0xFF, 0xFF, 0xFF, requester]) + pgn.to_bytes(3, "little")
        return TxRequest(PGN_ACK, GLOBAL, data, "protocol")
