"""Public names of the step 2 modules built so far (docs/modules.md section 4)."""

from __future__ import annotations

import inspect

import j1939logger.config as config
import j1939logger.store as store
from j1939logger.admin import DiagLog
from j1939logger.clock import Clock
from j1939logger.store import Store


def _public(cls: type) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


def test_SC_6_config_public_names() -> None:
    assert {"validate", "validate_inventory", "validate_library", "Config", "ConfigError"} <= set(
        config.__all__
    )
    assert list(inspect.signature(config.validate).parameters) == ["new", "old"]


def test_SC_6_store_public_names() -> None:
    assert {"Store", "CardUsage"} <= set(store.__all__)
    assert {"load", "write_atomic", "versions", "usage", "free"} <= _public(Store)
    assert store.KINDS == ("status", "inventory", "config", "library", "state")  # DC-10


def test_SC_6_clock_v2_adds_veh_time_and_elapsed_s() -> None:
    assert {"now", "mono", "to_utc", "veh_time", "elapsed_s", "on_time_date"} <= _public(Clock)


def test_SC_6_admin_diag_log_public_names() -> None:
    assert {"log", "flush", "restart_cause", "last_restart_cause"} <= _public(DiagLog)


def test_SC_6_session_and_eventlog_step_2_public_names() -> None:
    from j1939logger.eventlog import EventLog, scan_tail
    from j1939logger.session import Session

    assert {"start", "step", "run", "stop"} <= _public(Session)
    assert {"append", "sync_now", "start_sync", "stop_sync", "roll_over", "close"} <= _public(
        EventLog
    )
    assert callable(scan_tail)
