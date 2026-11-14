"""DET-19: detect with generated claims, moves, replies and floods of new addresses (Hypothesis).

Properties: no unhandled exception; every record is a detect record type; a
connection is open at most once per key; every ``connection_end`` belongs to a
connection that was started, and ``end_all`` leaves none open.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from j1939logger.clock import Clock
from j1939logger.config import Inventory, InventoryEntry
from j1939logger.detect import Detect
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.types import J1939Msg

SETTINGS = {
    "detection.silence_end_s": 60,
    "detection.move_grace_s": 1,
    "detection.first_sweep_wait_s": 10,
    "classify.wake_window_s": 10,
}
NAMES = [0x000000002E412A10, 0x000003001D20B4F1, 0x8000FE003C04D2E8, 0x8000810033A1B2C4, 7]
INVENTORY = Inventory(
    "inv-v9",
    "VIN",
    (
        InventoryEntry("E01", NAMES[0], "vehicle ECU in baseline", (0,)),
        InventoryEntry("E02", NAMES[1], "vehicle ECU in baseline", (3,)),
        InventoryEntry("E04", NAMES[2], "external device (approved)", (238,)),
        InventoryEntry("E09", None, "external device (approved)", (40,)),
    ),
)
TYPES = {"connection_start", "connection_end", "address_change", "address_conflict"}

addresses = st.integers(min_value=0, max_value=255)


@st.composite
def events(draw: st.DrawFn) -> tuple[str, object]:
    kind = draw(st.sampled_from(["claim", "frame", "reply", "poll", "sweep", "no_sweep"]))
    t = draw(st.floats(min_value=0, max_value=500, allow_nan=False))
    sa, da = draw(addresses), draw(addresses)
    if kind == "claim":
        name = draw(st.one_of(st.sampled_from(NAMES), st.integers(0, 2**64 - 1)))
        data = draw(st.one_of(st.just(name.to_bytes(8, "little")), st.binary(max_size=10)))
        return kind, J1939Msg(t, 0, 6, 60928, sa, 255, data, False, draw(st.booleans()), False)
    if kind in ("frame", "reply"):
        pgn = draw(st.integers(0, 0x3FFFF))
        own, to_logger = draw(st.booleans()), draw(st.booleans())
        return kind, J1939Msg(t, 0, 3, pgn, sa, da, b"", False, own, to_logger)
    return kind, t


@settings(max_examples=300)
@given(st.lists(events(), max_size=150), st.booleans())
def test_DET_19_detect_never_raises_and_keeps_connections_consistent(
    batch: list[tuple[str, object]], trained: bool
) -> None:
    with tempfile.TemporaryDirectory() as d:
        fc = FakeClock(start_utc=datetime(2026, 11, 6, tzinfo=timezone.utc), start_mono=0.0)
        det = Detect(
            Clock(DesktopPlatform(clock=fc, root=Path(d)), 5),
            SETTINGS,
            INVENTORY if trained else None,
            summary=lambda c: {"pgns_sent": []},
            ready_mono=0.0,
        )
        opened: set[int] = set()
        records = []
        for kind, item in batch:
            if isinstance(item, J1939Msg):
                records += det.on_message(item, 247)
            elif kind == "poll":
                records += det.poll(float(item))  # type: ignore[arg-type]
            elif kind == "sweep":
                records += det.sweep_complete(float(item))  # type: ignore[arg-type]
            else:
                det.no_sweep()
            keys = [c.key for c in det.connections]
            assert len(keys) == len(set(keys))
        records += det.end_all("key-off")
        assert det.connections == []
        for r in records:
            assert r.type in TYPES
            if r.type == "connection_start":
                assert r.conn not in opened
                opened.add(r.conn)  # type: ignore[arg-type]
            elif r.type == "connection_end":
                assert r.conn in opened
