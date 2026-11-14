"""Public names of the step 6 modules (docs/modules.md section 4, frozen for step 6)."""

from __future__ import annotations

import inspect

import j1939logger.inventory as inventory
from j1939logger.inventory import Training


def _public(cls: type) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


def test_SC_6_inventory_public_names() -> None:
    names = {"Training", "condition", "next_version", "next_entry_id", "approve", "remove"}
    assert names | {"confirm_record", "rejection_record", "InventoryRefused"} <= set(
        inventory.__all__
    )
    assert {"observe", "identity", "observing", "coverage", "propose"} <= _public(Training)


def test_SC_6_rawcap_and_retention_public_names() -> None:
    import j1939logger.rawcap as rawcap
    import j1939logger.retention as retention
    from j1939logger.rawcap import RawCap
    from j1939logger.retention import Retention

    assert {"RawCap", "candump_line"} <= set(rawcap.__all__)
    assert {"start", "feed", "poll", "close", "stop", "take_faults"} <= _public(RawCap)
    assert {"Retention", "RawFile", "Plan"} <= set(retention.__all__)
    assert "check" in _public(Retention)
