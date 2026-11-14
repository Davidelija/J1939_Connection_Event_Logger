"""Public names of the step 4 modules (docs/modules.md section 4, frozen for step 4)."""

from __future__ import annotations

import inspect

import j1939logger.detect as detect
import j1939logger.monitor as monitor
from j1939logger.detect import Detect
from j1939logger.monitor import Monitor


def _public(cls: type) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


def test_SC_6_monitor_public_names() -> None:
    assert "Monitor" in monitor.__all__
    assert {"on_message", "summary", "end", "table_sizes"} <= _public(Monitor)
    assert isinstance(Monitor.open_transfers, property)  # DC-16


def test_SC_6_detect_public_names() -> None:
    assert detect.__all__ == ["Detect"]  # step 1's InventoryEntry retired (DC-13)
    assert {"on_message", "poll", "sweep_complete", "no_sweep", "end_all"} <= _public(Detect)
    assert {"connection_for", "entry_for", "name_at"} <= _public(Detect)
    assert isinstance(Detect.waiting, property) and isinstance(Detect.connections, property)
