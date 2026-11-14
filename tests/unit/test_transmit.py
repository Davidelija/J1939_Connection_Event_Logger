"""transmit: the guard, the rate cap, outstanding requests, transmit off (safety-critical)."""

from __future__ import annotations

import errno
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from j1939logger.clock import Clock
from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.session import settings_from_config
from j1939logger.transmit import (
    PGN_ACK,
    PGN_CLAIM,
    PGN_REQUEST,
    PGN_TP_CM,
    Transmit,
    can_id,
)
from j1939logger.types import TxRequest

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
NAME = 0x9FFEFFFFFFE00001
SA = 247


class Recorder:
    """Stands in for capture's send handle; records every frame sent."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.frames: list[tuple[float, int, bytes]] = []
        self.error = error
        self.clock: FakeClock | None = None

    def send(self, cid: int, data: bytes) -> None:
        if self.error is not None:
            raise self.error
        assert self.clock is not None
        self.frames.append((self.clock.mono(), cid, data))


def settings(**over: Any) -> dict[str, Any]:
    s = settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))
    s.update(over)
    return s


def make(
    tmp_path: Path,
    plan: Sequence[FaultSpec] = (),
    error: BaseException | None = None,
    over: dict[str, Any] | None = None,
) -> tuple[Transmit, Recorder, FakeClock]:
    fc = FakeClock(start_mono=100.0)
    p = DesktopPlatform(fault_plan=plan, clock=fc, root=tmp_path)
    tx = Transmit(p, Clock(p, 5), settings(**(over or {})), NAME)
    rec = Recorder(error)
    rec.clock = fc
    tx.enable(rec)
    tx.set_source(SA)
    return tx, rec, fc


def request(pgn: int, da: int = 0) -> TxRequest:
    return TxRequest(PGN_REQUEST, da, pgn.to_bytes(3, "little"), "request")


def claim() -> TxRequest:
    return TxRequest(PGN_CLAIM, 255, NAME.to_bytes(8, "little"), "protocol")


def nack(pgn: int, da: int) -> TxRequest:
    return TxRequest(
        PGN_ACK, da, bytes([1, 0xFF, 0xFF, 0xFF, da]) + pgn.to_bytes(3, "little"), "protocol"
    )


def tp_cm(control: int, da: int) -> TxRequest:
    return TxRequest(
        PGN_TP_CM,
        da,
        bytes([control, 1, 1, 0xFF, 0xFF]) + (65259).to_bytes(3, "little"),
        "protocol",
    )


def run(tx: Transmit, fc: FakeClock, seconds: float, step: float = 0.01) -> None:
    end = fc.mono() + seconds
    while fc.mono() < end:
        tx.pump()
        fc.advance(step)


# -- nothing before enable ------------------------------------------------------


def test_NP_17_nothing_is_sent_before_transmit_is_enabled(tmp_path: Path) -> None:
    fc = FakeClock()
    p = DesktopPlatform(clock=fc, root=tmp_path)
    tx = Transmit(p, Clock(p, 5), settings(), NAME)
    tx.set_source(SA)
    result = tx.submit(request(65260))
    assert not result.accepted and "not enabled" in (result.reason or "")
    assert tx.pump() == 0


# -- the guard (NP-9, NP-18) -----------------------------------------------------


@pytest.mark.parametrize(
    "req",
    [
        TxRequest(61444, 255, bytes(8), "protocol"),  # EEC1: provides data
        TxRequest(0, 0, bytes(8), "protocol"),  # TSC1: a command
        TxRequest(65235, 255, bytes(8), "protocol"),  # DM11: a clear
        TxRequest(PGN_REQUEST, 0, (65235).to_bytes(3, "little"), "request"),  # request a clear
        TxRequest(PGN_REQUEST, 0, (65226).to_bytes(3, "little"), "request"),  # not in the list
        TxRequest(PGN_CLAIM, 255, (0x8000810033A1B2C4).to_bytes(8, "little"), "protocol"),
        TxRequest(
            PGN_ACK, 0, bytes([0, 0xFF, 0xFF, 0xFF, 0, 0, 0xEE, 0]), "protocol"
        ),  # positive ACK
        TxRequest(
            PGN_TP_CM, 0, bytes([16, 20, 0, 3, 0xFF, 0, 0xEE, 0]), "protocol"
        ),  # RTS: sending data
        TxRequest(PGN_TP_CM, 255, bytes([32, 20, 0, 3, 0xFF, 0, 0xEE, 0]), "protocol"),  # BAM
        TxRequest(PGN_REQUEST, 0, (65260).to_bytes(3, "little"), "protocol"),  # wrong kind
        TxRequest(PGN_CLAIM, 255, NAME.to_bytes(8, "little"), "request"),  # wrong kind
        TxRequest(PGN_REQUEST, 0, (65260).to_bytes(3, "little"), "urgent"),  # unknown kind
    ],
)
def test_NP_9_breach_is_never_sent_and_turns_transmit_off(tmp_path: Path, req: TxRequest) -> None:
    tx, rec, fc = make(tmp_path)
    tx.submit(request(65260))  # queued before the breach
    result = tx.submit(req)
    assert not result.accepted
    assert not tx.enabled and tx.off_reason is not None and tx.off_reason.startswith("tx_breach")
    run(tx, fc, 2.0)
    assert rec.frames == []  # neither the breach nor anything queued
    [fault] = tx.take_faults()
    assert (fault.type, fault.sev) == ("fault", "high")


def test_NP_9_configured_allow_list_can_narrow_but_never_widen(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path, over={"transmit.allow_list": [59904, 60928, 59392, 60416, 61184]})
    assert not tx.submit(TxRequest(61184, 0, bytes(8), "protocol")).accepted  # not in the release
    tx2, _, _ = make(tmp_path / "b", over={"requests.allow_list": [60928]})
    assert not tx2.submit(request(65260)).accepted  # narrowed by config


def test_NP_9_only_cannot_claim_may_use_the_null_address(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    assert tx.submit(claim(), sa=254).accepted  # Cannot Claim
    run(tx, fc, 0.1)
    assert rec.frames[0][1] & 0xFF == 254
    tx2, _, _ = make(tmp_path / "b")
    assert not tx2.submit(request(65260), sa=254).accepted
    assert not tx2.enabled


def test_NP_9_allowed_frames_are_sent_with_the_right_identifiers(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    for req in (
        claim(),
        request(60928, 255),
        nack(65259, 0),
        tp_cm(17, 0),
        tp_cm(19, 0),
        tp_cm(255, 0),
    ):
        assert tx.submit(req).accepted
    run(tx, fc, 1.0)
    ids = [cid for _, cid, _ in rec.frames]
    assert ids[0] == can_id(PGN_CLAIM, SA, 255, 6) == 0x18EEFFF7
    assert can_id(PGN_REQUEST, SA, 255, 6) in ids
    assert can_id(PGN_TP_CM, SA, 0, 7) in ids
    assert tx.enabled
    assert tx.logger_tx() == {"claims": 1, "requests": 1, "tp_cts": 1, "tp_eoma": 1, "nacks": 1}


def test_NP_18_transmit_never_turns_back_on_in_the_session(tmp_path: Path) -> None:
    tx, rec, _ = make(tmp_path)
    tx.disable("bus_off")
    assert tx.enable(rec) is False
    assert not tx.submit(claim()).accepted


# -- rate cap and queueing (NP-16, NP-6) -----------------------------------------


def test_NP_16_30_queued_requests_never_exceed_10_frames_in_any_second(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    pgns = [65254, 65260, 65259, 65242, 64965]
    for i in range(30):
        tx.submit(request(pgns[i % 5], da=i))  # 30 destinations
    run(tx, fc, 5.0)
    times = [t for t, _, _ in rec.frames]
    assert len(times) == 30
    for t in times:
        assert sum(1 for u in times if t <= u < t + 1.0) <= 10


def test_NP_16_one_outstanding_request_per_destination_until_release(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    tx.submit(request(65259, da=3))
    tx.submit(request(65242, da=3))
    tx.submit(request(65259, da=4))
    run(tx, fc, 2.0)
    assert [d[0] | (d[1] << 8) | (d[2] << 16) for _, _, d in rec.frames] == [65259, 65259]
    tx.release(3)
    run(tx, fc, 0.5)
    assert len(rec.frames) == 3


def test_NP_16_global_requests_count_as_destination_255(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    tx.submit(request(60928, da=255))
    tx.submit(request(60928, da=255))
    run(tx, fc, 2.0)
    assert len(rec.frames) == 1


def test_NP_16_protocol_frames_go_ahead_of_queued_requests(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    for da in range(5):
        tx.submit(request(65259, da=da))
    tx.submit(nack(65226, 9))
    run(tx, fc, 0.1)
    assert rec.frames[0][1] == can_id(PGN_ACK, SA, 9, 6)


def test_NP_6_nothing_but_claims_for_250_ms_after_a_claim(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    tx.submit(claim())
    tx.submit(request(65260, da=0))
    run(tx, fc, 0.6, step=0.01)
    (t_claim, _, _), (t_req, _, _) = rec.frames
    assert t_req - t_claim >= 0.25


# -- send errors (NP-18) -----------------------------------------------------------


def test_NP_18_enobufs_on_send_turns_transmit_off(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path, error=OSError(errno.ENOBUFS, "No buffer space"))
    tx.submit(claim())
    run(tx, fc, 0.1)
    assert not tx.enabled and tx.off_reason == "enobufs on send"
    assert tx.take_faults()[0].sev == "high"


def test_NP_18_enobufs_from_the_fault_plan_turns_transmit_off(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path, plan=[(100.0, "enobufs", None)])
    tx.submit(claim())
    run(tx, fc, 0.1)
    assert rec.frames == [] and tx.off_reason == "enobufs on send"


def test_NP_3_bus_off_disable_drops_the_queue(tmp_path: Path) -> None:
    tx, rec, fc = make(tmp_path)
    tx.submit(request(65260, da=0))
    tx.disable("bus_off")
    run(tx, fc, 1.0)
    assert rec.frames == [] and tx.off_reason == "bus_off"
