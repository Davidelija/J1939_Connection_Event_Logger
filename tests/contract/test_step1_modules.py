"""Public names of the step 1 modules (docs/modules.md section 4, frozen for step 1)."""

from __future__ import annotations

import dataclasses
import inspect

import j1939logger.capture as capture
import j1939logger.clock as clock
import j1939logger.decode as decode
import j1939logger.eventlog as eventlog
from j1939logger.capture import Capture, CaptureStats
from j1939logger.clock import Clock
from j1939logger.decode import DecodeStats
from j1939logger.eventlog import EventLog


def _public(cls: type) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


def test_SC_6_capture_public_names() -> None:
    assert set(capture.__all__) == {"Capture", "CaptureStats", "parse_frame", "TransmitHandle"}
    assert {"read_batch", "window", "stats", "start", "stop", "set_mode"} <= _public(Capture)
    assert [f.name for f in dataclasses.fields(CaptureStats)] == [
        "kernel_drops",
        "rx_buffer_bytes",
        "frames",
    ]


def test_SC_6_decode_public_names() -> None:
    assert {"decode", "new_state", "decode_name", "DecodeStats", "DecodeState"} <= set(
        decode.__all__
    )
    assert [f.name for f in dataclasses.fields(DecodeStats)] == [
        "non_j1939",
        "tp_closed",
        "malformed",
        "etp_seen",
    ]
    params = list(inspect.signature(decode.decode).parameters)
    assert params[:2] == ["frames", "state"]


def test_SC_6_clock_public_names() -> None:
    assert "Clock" in clock.__all__
    assert {"now", "mono", "to_utc", "on_time_date"} <= _public(Clock)


def test_SC_6_eventlog_public_names() -> None:
    assert "EventLog" in eventlog.__all__
    assert {"append", "sync_now", "take_faults", "close"} <= _public(EventLog)
    assert isinstance(inspect.getattr_static(EventLog, "last_hash"), property)
