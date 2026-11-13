"""DesktopPlatform: the platform functions on the desktop and its fault plan."""

from __future__ import annotations

import os
import socket
import struct
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from j1939logger.platform.desktop import (
    DELIVERED_FAULT_KINDS,
    OPS_BY_KIND,
    DesktopPlatform,
    FakeClock,
    FaultSpec,
)
from j1939logger.platform.interface import FAULT_KINDS, FAULT_OPS, LIGHT_PATTERNS
from j1939logger.types import PlatformError

START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


def make(
    tmp_path: Path, plan: Sequence[FaultSpec] = (), **kw: Any
) -> tuple[DesktopPlatform, FakeClock]:
    clock = FakeClock(start_utc=START, start_mono=100.0)
    return DesktopPlatform(fault_plan=plan, clock=clock, root=tmp_path, **kw), clock


# -- time ------------------------------------------------------------------


def test_LOG_16_now_reads_the_fake_clock(tmp_path: Path) -> None:
    p, clock = make(tmp_path)
    r = p.now()
    assert (r.wall_utc, r.mono, r.source, r.valid) == (START, 100.0, "rtc", True)
    clock.advance(30.0)
    r = p.now()
    assert r.mono == 130.0
    assert r.wall_utc == START + timedelta(seconds=30)


def test_LOG_16_rtc_invalid_fault_gives_no_wall_time_and_elapsed_source(tmp_path: Path) -> None:
    p, clock = make(tmp_path, [(110.0, "rtc_invalid", None)])
    assert p.rtc_ok() is True
    clock.advance(10.0)
    assert p.rtc_ok() is False
    r = p.now()
    assert (r.wall_utc, r.mono, r.source, r.valid) == (None, 110.0, "elapsed", False)


def test_LOG_16_rtc_invalid_fault_window_ends_after_for_s(tmp_path: Path) -> None:
    p, clock = make(tmp_path, [(100.0, "rtc_invalid", {"for_s": 5.0})])
    assert p.rtc_ok() is False
    clock.advance(5.0)
    assert p.rtc_ok() is True


def test_LOG_16_clock_jump_fault_steps_wall_time_at_its_moment(tmp_path: Path) -> None:
    p, clock = make(tmp_path, [(160.0, "clock_jump", {"s": -3600.0})])
    clock.advance(59.0)
    assert p.now().wall_utc == START + timedelta(seconds=59)
    clock.advance(2.0)  # crosses 160.0
    r = p.now()
    assert r.mono == 161.0
    assert r.wall_utc == START + timedelta(seconds=61) - timedelta(hours=1)


def test_LOG_16_clock_jump_fault_needs_a_fake_clock_and_seconds(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        DesktopPlatform(fault_plan=[(1.0, "clock_jump", {"s": 5})], root=tmp_path)
    with pytest.raises(ValueError):
        make(tmp_path, [(1.0, "clock_jump", {})])


def test_LOG_16_host_clock_used_without_fake_clock(tmp_path: Path) -> None:
    p = DesktopPlatform(root=tmp_path)
    a = p.now()
    b = p.now()
    assert a.source == "rtc" and a.valid and a.wall_utc is not None
    assert a.wall_utc.tzinfo is not None
    assert b.mono >= a.mono


def test_HW_8_on_wake_reports_wake_and_ready_times(tmp_path: Path) -> None:
    p, clock = make(tmp_path)
    clock.advance(3.8)
    wake, ready = p.on_wake()
    assert wake == 100.0
    assert ready == pytest.approx(103.8)
    clock.advance(10.0)
    assert p.on_wake() == (wake, ready)  # ready time is fixed once reported


# -- CAN -------------------------------------------------------------------


def test_NP_17_no_bitrate_fault_gives_none_while_active(tmp_path: Path) -> None:
    p, clock = make(tmp_path, [(100.0, "no_bitrate", {"for_s": 60.0})])
    assert p.bitrate_check() is None
    clock.advance(59.9)
    assert p.bitrate_check() is None
    clock.advance(0.1)
    assert p.bitrate_check() == 250000


def test_PLT_2_desktop_bitrate_check_returns_configured_rate(tmp_path: Path) -> None:
    p, _ = make(tmp_path, bitrate=500000)
    assert p.bitrate_check() == 500000


def test_NP_17_can_missing_fault_raises_platform_error(tmp_path: Path) -> None:
    p, _ = make(tmp_path, [(100.0, "can_missing", None)])
    with pytest.raises(PlatformError) as exc:
        p.open_can(listen_only=True)
    assert exc.value.kind == "can_missing"


def test_NP_17_missing_interface_raises_can_missing(tmp_path: Path) -> None:
    p, _ = make(tmp_path, interface="nosuchcan9")
    with pytest.raises(PlatformError) as exc:
        p.open_can(listen_only=True)
    assert exc.value.kind == "can_missing"


_VCAN = sys.platform.startswith("linux") and os.path.exists("/sys/class/net/vcan0")
needs_vcan = pytest.mark.skipif(not _VCAN, reason="needs Linux with vcan0 up (CI loads it)")
_FMT = "=IB3x8s"
_EFF = 0x80000000
_MSG_CONFIRM = 0x800


def _recv(sock: socket.socket) -> tuple[int, bytes, int, list[tuple[int, int, bytes]]]:
    sock.settimeout(2.0)
    data, anc, flags, _ = sock.recvmsg(16, socket.CMSG_SPACE(16) + socket.CMSG_SPACE(4))
    can_id, dlc, payload = struct.unpack(_FMT, data)
    return can_id, payload[:dlc], flags, anc


@needs_vcan
def test_PLT_2_open_can_receives_timestamped_frames_on_vcan0(tmp_path: Path) -> None:
    p, _ = make(tmp_path)
    rx = p.open_can(listen_only=True)
    tx = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        tx.bind(("vcan0",))
        tx.send(struct.pack(_FMT, 0x18EEFFF9 | _EFF, 8, bytes(range(8))))
        can_id, payload, flags, anc = _recv(rx)
        assert can_id == 0x18EEFFF9 | _EFF
        assert payload == bytes(range(8))
        assert not flags & _MSG_CONFIRM  # not sent by this socket
        levels = {(lvl, typ) for lvl, typ, _ in anc}
        assert (socket.SOL_SOCKET, 29) in levels  # SO_TIMESTAMP ancillary data
        assert p.listen_only is True
    finally:
        rx.close()
        tx.close()


@needs_vcan
def test_PLT_2_open_can_marks_own_frames_on_vcan0(tmp_path: Path) -> None:
    p, _ = make(tmp_path)
    sock = p.open_can(listen_only=False)
    try:
        sock.send(struct.pack(_FMT, 0x18EAFFFE | _EFF, 3, b"\x00\xee\x00" + bytes(5)))
        can_id, _, flags, _ = _recv(sock)
        assert can_id == 0x18EAFFFE | _EFF
        assert flags & _MSG_CONFIRM  # own frame: Frame.own
    finally:
        sock.close()


# -- light, watchdog, paths --------------------------------------------------


def test_STS_1_set_light_records_each_pattern(tmp_path: Path) -> None:
    p, _ = make(tmp_path)
    for pattern in LIGHT_PATTERNS:
        p.set_light(pattern)
    assert p.lights == list(LIGHT_PATTERNS)


def test_STS_1_set_light_rejects_unknown_pattern(tmp_path: Path) -> None:
    p, _ = make(tmp_path)
    with pytest.raises(ValueError):
        p.set_light("blink")


def test_STS_18_watchdog_kicks_are_counted(tmp_path: Path) -> None:
    p, _ = make(tmp_path)
    p.watchdog_kick()
    p.watchdog_kick()
    assert p.watchdog_kicks == 2


def test_PLT_5_paths_give_separate_card_flash_and_keys(tmp_path: Path) -> None:
    p, _ = make(tmp_path)
    paths = p.paths()
    assert {paths.card, paths.flash, paths.keys} == {
        tmp_path / "card",
        tmp_path / "flash",
        tmp_path / "keys",
    }
    assert all(d.is_dir() for d in (paths.card, paths.flash, paths.keys))


def test_PLT_5_paths_default_to_a_new_temporary_folder() -> None:
    a = DesktopPlatform().paths()
    b = DesktopPlatform().paths()
    assert a.card != b.card and a.card.is_dir()


# -- the fault plan itself ---------------------------------------------------


def test_PLT_2_fault_plan_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make(tmp_path, [(1.0, "card_pulled", None)])


def test_PLT_2_fault_plan_rejects_malformed_entry(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make(tmp_path, [(1.0, "no_bitrate")])  # type: ignore[list-item]


@pytest.mark.parametrize("kind", [k for k in FAULT_KINDS if k not in DELIVERED_FAULT_KINDS])
def test_PLT_2_fault_plan_refuses_kinds_without_a_delivery_path(tmp_path: Path, kind: str) -> None:
    # DC-5 leaves these kinds to other injection points; refusing them stops a
    # test from believing a fault was injected when it was not.
    with pytest.raises(NotImplementedError, match="DC-5"):
        make(tmp_path, [(1.0, kind, None)])


def test_PLT_2_delivered_kinds_are_spelled_as_in_errors_md() -> None:
    assert set(DELIVERED_FAULT_KINDS) <= set(FAULT_KINDS)


# -- fault(op): socket and storage errors (DC-5) ------------------------------


@pytest.mark.parametrize("kind", [k for k in OPS_BY_KIND if k != "slow_sync"])
def test_PLT_2_fault_op_raises_each_planned_kind_on_its_operations(
    tmp_path: Path, kind: str
) -> None:
    p, clock = make(tmp_path, [(110.0, kind, None)])
    for op in FAULT_OPS:
        p.fault(op)  # not active yet: nothing raised
    clock.advance(10.0)
    for op in FAULT_OPS:
        if op in OPS_BY_KIND[kind]:
            with pytest.raises(PlatformError) as exc:
                p.fault(op)
            assert exc.value.kind == kind
        else:
            p.fault(op)


def test_LOG_22_card_removed_fault_window_ends_after_for_s(tmp_path: Path) -> None:
    p, clock = make(tmp_path, [(100.0, "card_removed", {"for_s": 2.0})])
    with pytest.raises(PlatformError):
        p.fault("card_write")
    clock.advance(2.0)
    p.fault("card_write")  # card reinserted


def test_LOG_22_fault_ops_arg_narrows_the_operations(tmp_path: Path) -> None:
    p, _ = make(tmp_path, [(100.0, "eio", {"ops": ["card_sync"]})])
    p.fault("card_write")
    with pytest.raises(PlatformError):
        p.fault("card_sync")
    with pytest.raises(ValueError):
        make(tmp_path, [(100.0, "eio", {"ops": ["can_send"]})])


def test_LOG_3_slow_sync_fault_delays_card_sync_by_s(tmp_path: Path) -> None:
    p, clock = make(tmp_path, [(100.0, "slow_sync", {"s": 3.5, "for_s": 1.0})])
    p.fault("card_write")
    assert clock.mono() == 100.0
    p.fault("card_sync")
    assert clock.mono() == pytest.approx(103.5)
    p.fault("card_sync")  # window over
    assert clock.mono() == pytest.approx(103.5)
    with pytest.raises(ValueError):
        make(tmp_path, [(1.0, "slow_sync", None)])


def test_LOG_5_state_unwritable_fault_hits_flash_only(tmp_path: Path) -> None:
    p, _ = make(tmp_path, [(100.0, "state_unwritable", None)])
    p.fault("card_write")
    with pytest.raises(PlatformError) as exc:
        p.fault("flash_write")
    assert exc.value.kind == "state_unwritable"


def test_PLT_2_fault_rejects_unknown_operation(tmp_path: Path) -> None:
    p, _ = make(tmp_path)
    with pytest.raises(ValueError):
        p.fault("card_read")
