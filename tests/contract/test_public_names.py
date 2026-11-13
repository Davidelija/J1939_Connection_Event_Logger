"""Public names (docs/modules.md sections 1 and 4): each module exports exactly its contract."""

from __future__ import annotations

import dataclasses
import typing

import j1939logger.platform.desktop as desktop
import j1939logger.platform.interface as interface
import j1939logger.types as types
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.platform.interface import FAULT_KINDS, LIGHT_PATTERNS, Paths, Platform
from j1939logger.types import (
    ClockReading,
    Connection,
    Frame,
    J1939Msg,
    Name,
    PlatformError,
    Record,
)

# Field names and order are the contract (docs/modules.md section 1).
CONTRACT_FIELDS = {
    Frame: ["ts_kernel", "ts_mono", "can_id", "extended", "remote", "error", "data", "own"],
    J1939Msg: [
        "ts_mono", "ts_kernel", "priority", "pgn", "sa", "da", "data", "via_tp", "own",
        "reply_to_logger",
    ],
    Name: [
        "value", "aac", "industry_group", "vs_instance", "vehicle_system", "function",
        "function_instance", "ecu_instance", "mfr_code", "identity",
    ],
    ClockReading: ["wall_utc", "mono", "source", "valid"],
    Record: ["type", "sev", "utc", "veh_time", "fields", "conn", "event_id"],
    Connection: ["conn", "key", "sa", "name", "start_mono", "last_mono", "category"],
}  # fmt: skip

FROZEN = {Frame, J1939Msg, Name, ClockReading}


def test_SC_6_types_exports_exactly_the_contract_names() -> None:
    expected = {"Frame", "J1939Msg", "Name", "ClockReading", "Record", "Connection"}
    expected |= {"PlatformError"}
    enums = {n for n in types.__all__ if n.isupper()}
    assert set(types.__all__) == expected | enums
    assert all(isinstance(getattr(types, n), tuple) for n in enums)


def test_SC_6_shared_type_fields_match_the_contract() -> None:
    for cls, names in CONTRACT_FIELDS.items():
        assert [f.name for f in dataclasses.fields(cls)] == names, cls.__name__
        assert cls.__dataclass_params__.frozen == (cls in FROZEN), cls.__name__  # type: ignore[attr-defined]


def test_SC_6_shared_type_hints_evaluate_on_python_39() -> None:
    # Hypothesis and other tools call get_type_hints at run time (DC-1).
    for cls in CONTRACT_FIELDS:
        hints = typing.get_type_hints(cls)
        assert set(hints) == set(CONTRACT_FIELDS[cls])


def test_SC_6_platform_error_carries_kind() -> None:
    err = PlatformError("card_removed", "while syncing")
    assert err.kind == "card_removed"
    assert "card_removed" in str(err)
    assert isinstance(err, Exception)


def test_SC_6_platform_interface_exports_exactly_the_contract_names() -> None:
    assert set(interface.__all__) == {"Platform", "Paths", "LIGHT_PATTERNS", "FAULT_KINDS"}
    assert LIGHT_PATTERNS == ("steady", "slow", "fast", "off")
    assert [f.name for f in dataclasses.fields(Paths)] == ["card", "flash", "keys"]
    assert len(set(FAULT_KINDS)) == len(FAULT_KINDS)


def test_SC_6_platform_protocol_has_exactly_the_eight_functions() -> None:
    members = {n for n in vars(Platform) if not n.startswith("_")}
    assert members == {
        "open_can", "bitrate_check", "set_light", "now", "rtc_ok", "on_wake",
        "watchdog_kick", "paths",
    }  # fmt: skip


def test_SC_6_desktop_exports_the_test_seam() -> None:
    assert {"DesktopPlatform", "FakeClock"} <= set(desktop.__all__)
    assert callable(FakeClock.advance) and callable(FakeClock.jump)
    assert callable(DesktopPlatform)
