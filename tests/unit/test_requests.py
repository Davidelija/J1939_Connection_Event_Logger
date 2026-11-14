"""requests: sweep, Time/Date, VIN, identity, timeouts and retry, outcomes, sweep records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from j1939logger.clock import Clock
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.requests import (
    PGN_COMPONENT_ID,
    PGN_ECU_ID,
    PGN_SOFTWARE_ID,
    PGN_TIME_DATE,
    PGN_VIN,
    Requests,
)
from j1939logger.session import settings_from_config
from j1939logger.types import J1939Msg, TxRequest

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
NAME = 0x9FFEFFFFFFE00001
ENGINE = 0x000000002E412A10
SCAN = 0x8000810033A1B2C4
LOGGER_SA = 247


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def make(tmp_path: Path) -> tuple[Requests, FakeClock, list[int]]:
    fc = FakeClock(start_mono=100.0)
    p = DesktopPlatform(clock=fc, root=tmp_path)
    released: list[int] = []
    r = Requests(Clock(p, 5), settings(), {ENGINE}, NAME, released.append)
    return r, fc, released


def wanted(req: TxRequest) -> int:
    return int.from_bytes(req.data, "little")


def reply(pgn: int, sa: int, data: bytes = b"\x01" * 8, da: int = LOGGER_SA) -> J1939Msg:
    return J1939Msg(100.0, 0.0, 6, pgn, sa, da, data, len(data) > 8, False, da == LOGGER_SA)


def nack(pgn: int, sa: int) -> J1939Msg:
    data = bytes([1, 0xFF, 0xFF, 0xFF, LOGGER_SA]) + pgn.to_bytes(3, "little")
    return J1939Msg(100.0, 0.0, 6, 59392, sa, 255, data, False, False, False)


def claim(name: int, sa: int) -> J1939Msg:
    return J1939Msg(100.0, 0.0, 6, 60928, sa, 255, name.to_bytes(8, "little"), False, False, False)


def test_NP_11_session_start_sweeps_then_asks_time_date_and_vin_of_vin_sa(tmp_path: Path) -> None:
    r, fc, _ = make(tmp_path)
    r.session_start()
    first = r.poll()
    assert sorted((q.da, wanted(q)) for q in first) == [(0, PGN_TIME_DATE), (255, 60928)]
    assert all(q.pgn == 59904 and q.kind == "request" for q in first)
    r.on_message(reply(PGN_TIME_DATE, 0), LOGGER_SA)
    [vin] = r.poll()
    assert (vin.da, wanted(vin)) == (0, PGN_VIN)  # one request per destination at a time


def test_NP_11_sweep_repeats_every_10_minutes(tmp_path: Path) -> None:
    r, fc, _ = make(tmp_path)
    r.session_start()
    r.poll()
    fc.advance(2.0)
    r.poll()
    fc.advance(600.0)
    assert any(q.da == 255 and wanted(q) == 60928 for q in r.poll())


def test_NP_14_timeout_retry_once_then_no_reply_and_never_repeated(tmp_path: Path) -> None:
    r, fc, released = make(tmp_path)
    r.identify(conn=2, sa=0xF9, name=SCAN)
    [q1] = r.poll()
    assert wanted(q1) == PGN_COMPONENT_ID
    fc.advance(1.3)
    [q2] = r.poll()  # the retry
    assert wanted(q2) == PGN_COMPONENT_ID
    fc.advance(1.3)
    nxt = r.poll()  # gives up; next identity request goes out
    [out] = r.take_outcomes()
    assert (out.conn, out.pgn, out.outcome, out.attempts) == (2, PGN_COMPONENT_ID, "no reply", 2)
    assert [wanted(q) for q in nxt] == [PGN_SOFTWARE_ID]
    assert released.count(0xF9) == 2
    r.identify(conn=2, sa=0xF9, name=SCAN)  # not asked again in this session
    r.on_message(reply(PGN_SOFTWARE_ID, 0xF9), LOGGER_SA)
    r.on_message(nack(PGN_ECU_ID, 0xF9), LOGGER_SA)
    fc.advance(0.1)
    r.poll()
    r.on_message(nack(PGN_ECU_ID, 0xF9), LOGGER_SA)
    assert [(o.pgn, o.outcome) for o in r.take_outcomes()] == [
        (PGN_SOFTWARE_ID, "reply"),
        (PGN_ECU_ID, "NACK"),
    ]
    fc.advance(5)
    assert r.poll() == []


def test_NP_13_known_name_is_not_asked_for_identity(tmp_path: Path) -> None:
    r, _, _ = make(tmp_path)
    r.identify(conn=1, sa=0x05, name=ENGINE)  # a known NAME at a new address
    assert r.poll() == []
    r.identify(conn=2, sa=0xF9, name=SCAN)
    assert [wanted(q) for q in r.poll()] == [PGN_COMPONENT_ID]


def test_NP_14_reply_value_is_kept_for_identify(tmp_path: Path) -> None:
    r, _, released = make(tmp_path)
    r.identify(conn=2, sa=0xF9, name=None)  # never claims: asked by address
    r.poll()
    r.on_message(reply(PGN_COMPONENT_ID, 0xF9, b"ACME*CR-200*SN1*"), LOGGER_SA)
    [out] = r.take_outcomes()
    assert (out.outcome, out.value) == ("reply", b"ACME*CR-200*SN1*")
    assert released == [0xF9]


def test_LOG_9_first_sweep_is_logged_then_only_changes(tmp_path: Path) -> None:
    r, fc, _ = make(tmp_path)
    r.session_start()
    r.poll()
    r.on_message(claim(ENGINE, 0), LOGGER_SA)
    r.on_message(claim(NAME, LOGGER_SA), LOGGER_SA)  # the logger is listed separately
    fc.advance(1.3)
    r.poll()
    [first] = r.take_records()
    assert (first.type, first.sev, first.fields["first"]) == ("sweep", "info", True)
    assert first.fields["names"] == [f"0x{ENGINE:016X}"] and first.fields["in_inventory"] == 1
    assert first.fields["logger"] == f"0x{NAME:016X}"
    assert r.first_sweep_done
    fc.advance(600)
    r.poll()
    r.on_message(claim(ENGINE, 0), LOGGER_SA)
    fc.advance(1.3)
    r.poll()
    assert r.take_records() == []  # no change: not logged
    fc.advance(600)
    r.poll()
    r.on_message(claim(ENGINE, 0), LOGGER_SA)
    r.on_message(claim(SCAN, 0xF9), LOGGER_SA)
    fc.advance(1.3)
    r.poll()
    [change] = r.take_records()
    assert (change.sev, change.fields["added"]) == ("notice", [f"0x{SCAN:016X}"])
    assert (r.sweeps, r.sweeps_logged) == (3, 2)


def test_NP_9_never_requests_outside_the_request_allow_list(tmp_path: Path) -> None:
    fc = FakeClock()
    p = DesktopPlatform(clock=fc, root=tmp_path)
    s = settings()
    s["requests.allow_list"] = [60928, 65254]
    r = Requests(Clock(p, 5), s, set(), NAME, lambda da: None)
    r.session_start()
    r.identify(conn=1, sa=0xF9, name=SCAN)
    assert {wanted(q) for q in r.poll()} == {60928, 65254}
