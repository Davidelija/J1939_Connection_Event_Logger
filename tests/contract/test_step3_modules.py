"""Public names of the step 3 modules (docs/modules.md section 4, frozen for step 3)."""

from __future__ import annotations

import inspect

import j1939logger.address as address
import j1939logger.requests as requests
import j1939logger.transmit as transmit
from j1939logger.address import Address
from j1939logger.requests import Requests
from j1939logger.transmit import Transmit


def _public(cls: type) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


def test_SC_6_transmit_public_names() -> None:
    assert {"Transmit", "TxResult", "RELEASE_TRANSMIT_ALLOW", "RELEASE_REQUEST_ALLOW"} <= set(
        transmit.__all__
    )
    assert {"submit", "pump", "release", "enable", "disable", "logger_tx"} <= _public(Transmit)


def test_SC_6_address_public_names() -> None:
    assert "Address" in address.__all__
    assert {"start", "on_message"} <= _public(Address)


def test_SC_6_requests_public_names() -> None:
    assert {"Requests", "RequestOutcome"} <= set(requests.__all__)
    assert {"session_start", "identify", "poll", "on_message", "take_outcomes"} <= _public(Requests)
