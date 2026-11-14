"""SC-12a: monitor with generated malformed messages and transfers (Hypothesis).

Properties: no unhandled exception, every record is a known type, the PGN
table never exceeds limits.pgns_per_conn, open ETP transfers never exceed
limits.tp_sessions, kept requests never exceed detection.requests_kept, and
the summary always serializes to JSON.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from j1939logger.clock import Clock
from j1939logger.config import InventoryEntry
from j1939logger.monitor import Monitor
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.types import Connection, J1939Msg

TP, TABLE, KEPT = 3, 8, 5
LIMITS = {
    "detection.control_pgns": [0, 256, 1024, 65240, 56832, 65235],
    "detection.requests_kept": KEPT,
    "detection.known_device_new_pgn": True,
    "limits.pgns_per_conn": TABLE,
    "limits.tp_sessions": TP,
}
CONNS = [
    Connection(1, ("sa", 249), 249, None, 0.0, 0.0, "external device (unrecognized)"),
    Connection(2, ("name", 7), 238, None, 0.0, 0.0, "external device (approved)"),
]
RAW = {"requests_trained": [65260], "pgns_approved": [{"kind": "x"}, 5]}  # malformed approvals
ENTRY = InventoryEntry("E04", 7, "external device (approved)", (238,), (59904,), RAW)
ECU = InventoryEntry("E01", None, "vehicle ECU in baseline", (0,), (61444,), {"pgns_sent": "bad"})
TYPES = {"control_flag", "known_device_new_pgn"}

addresses = st.sampled_from([0, 3, 11, 238, 249, 254, 255])
pgns = st.one_of(
    st.sampled_from([0, 256, 1024, 51200, 50944, 59904, 61184, 65235, 65280, 55552, 54272]),
    st.integers(min_value=0, max_value=0x3FFFF),
)


@st.composite
def messages(draw: st.DrawFn) -> tuple[J1939Msg, Optional[Connection], Optional[InventoryEntry]]:
    pgn = draw(pgns)
    if pgn == 51200 and draw(st.booleans()):
        control = draw(st.sampled_from([20, 21, 22, 23, 255, 0, 99]))
        rest = draw(st.binary(min_size=0, max_size=9))
        data = bytes([control]) + rest
    else:
        data = draw(st.binary(min_size=0, max_size=12))
    m = J1939Msg(
        draw(st.floats(min_value=0, max_value=1e6, allow_nan=False)),
        0.0,
        draw(st.integers(min_value=0, max_value=7)),
        pgn,
        draw(addresses),
        draw(addresses),
        data,
        draw(st.booleans()),
        draw(st.booleans()),
        draw(st.booleans()),
    )
    conn = draw(st.sampled_from([None, *CONNS]))
    entry = draw(st.sampled_from([None, ENTRY, ECU]))
    return m, conn, entry


@settings(max_examples=300)
@given(st.lists(messages(), max_size=200))
def test_SC_12a_monitor_never_raises_and_stays_within_the_limits(batch: list) -> None:  # type: ignore[type-arg]
    with tempfile.TemporaryDirectory() as d:
        fc = FakeClock(start_utc=datetime(2026, 11, 6, tzinfo=timezone.utc), start_mono=0.0)
        mon = Monitor(Clock(DesktopPlatform(clock=fc, root=Path(d)), 5), LIMITS)
        for m, conn, entry in batch:
            for rec in mon.on_message(m, conn, entry):
                assert rec.type in TYPES
            assert mon.open_transfers <= TP
            assert all(n <= TABLE for n in mon.table_sizes())
        for c in CONNS:
            s = mon.end(c.conn)
            json.dumps(s)
            assert len(s.get("requests_first_100", [])) <= KEPT
