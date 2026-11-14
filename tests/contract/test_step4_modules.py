"""Public names of the step 4 modules (docs/modules.md section 4, frozen for step 4)."""

from __future__ import annotations

import inspect

import j1939logger.monitor as monitor
from j1939logger.monitor import Monitor


def _public(cls: type) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


def test_SC_6_monitor_public_names() -> None:
    assert "Monitor" in monitor.__all__
    assert {"on_message", "summary", "end"} <= _public(Monitor)
