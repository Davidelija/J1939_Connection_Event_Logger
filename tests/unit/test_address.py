"""address: choosing, claiming, conceding, Cannot Claim, answers and NACKs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from j1939logger.address import NULL_SA, PGN_ACK, PGN_CLAIM, Address
from j1939logger.clock import Clock
from j1939logger.decode import decode_name
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import settings_from_config
from j1939logger.types import J1939Msg

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
NAME = 0x9FFEFFFFFFE00001
ENGINE = 0x000000002E412A10


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def make(tmp_path: Path, inventory_addresses: tuple[int, ...] = (0, 3, 11, 238)) -> Address:
    p = DesktopPlatform(clock=FakeClock(), root=tmp_path)
    return Address(Clock(p, 5), settings(), NAME, inventory_addresses)


def claim(name: int, sa: int) -> J1939Msg:
    return J1939Msg(
        100.0, 0.0, 6, PGN_CLAIM, sa, 255, name.to_bytes(8, "little"), False, False, False
    )


def request(pgn: int, sa: int, da: int) -> J1939Msg:
    return J1939Msg(
        100.0, 0.0, 6, 59904, sa, da, pgn.to_bytes(3, "little"), False, False, da == 247
    )


def test_NP_5_logger_name_is_arbitrary_address_capable_and_maximal() -> None:
    n = decode_name(int(settings()["address.name"], 16))
    assert (n.aac, n.industry_group) == (1, 1)  # on-highway
    assert (n.function, n.mfr_code, n.vehicle_system, n.vs_instance) == (255, 2047, 127, 15)
    assert (n.function_instance, n.ecu_instance) == (31, 7)


def test_NP_4_claims_247_first_with_the_logger_name(tmp_path: Path) -> None:
    a = make(tmp_path)
    [(req, sa)] = a.start()
    assert (req.pgn, req.da, sa) == (PGN_CLAIM, 255, 247)
    assert req.data == NAME.to_bytes(8, "little")
    assert a.current == 247


def test_NP_4_skips_inventory_claimed_and_reserved_addresses(tmp_path: Path) -> None:
    a = make(tmp_path, inventory_addresses=(247, 246))
    a.on_message(claim(ENGINE + 1, 245))  # claimed this session
    [(_, sa)] = a.start()
    assert sa == 244
    p = DesktopPlatform(clock=FakeClock(), root=tmp_path / "b")
    s = settings()
    s["address.claim_from"] = 142  # reserved (128, 142): skipped
    b = Address(Clock(p, 5), s, NAME, ())
    [(_, sa2)] = b.start()
    assert sa2 == 141


def test_NP_7_concedes_tries_once_more_then_cannot_claim(tmp_path: Path) -> None:
    a = make(tmp_path)
    a.start()
    sends, [rec] = a.on_message(claim(ENGINE, 247))  # a vehicle NAME takes 247
    assert (rec.type, rec.sev, rec.fields["cause"]) == (
        "address_conflict",
        "notice",
        "the logger lost its claim",
    )
    [(req, sa)] = sends
    assert sa == 246 and a.current == 246
    sends, [rec2] = a.on_message(claim(ENGINE + 7, 246))
    [(req2, sa2)] = sends
    assert (req2.pgn, sa2) == (PGN_CLAIM, NULL_SA)  # Cannot Claim
    assert a.lost and a.current is None
    assert "Cannot Claim" in rec2.fields["logger_action"]


def test_NP_8_answers_request_for_address_claim(tmp_path: Path) -> None:
    a = make(tmp_path)
    a.start()
    sends, _ = a.on_message(request(PGN_CLAIM, 0xF9, 255))
    assert [(r.pgn, sa) for r, sa in sends] == [(PGN_CLAIM, 247)]
    sends, _ = a.on_message(request(PGN_CLAIM, 0xF9, 247))
    assert [(r.pgn, sa) for r, sa in sends] == [(PGN_CLAIM, 247)]


def test_NP_8_nacks_other_requests_to_the_logger_and_ignores_global_ones(tmp_path: Path) -> None:
    a = make(tmp_path)
    a.start()
    [(nack, sa)] = a.on_message(request(65260, 0xF9, 247))[0]
    assert (nack.pgn, nack.da, sa, nack.data[0], nack.data[4]) == (PGN_ACK, 255, 247, 1, 0xF9)
    assert int.from_bytes(nack.data[5:8], "little") == 65260
    assert a.on_message(request(65260, 0xF9, 255)) == ([], [])  # global: no answer
    assert a.on_message(request(65260, 0xF9, 3)) == ([], [])  # to someone else


def test_NP_8_commanded_address_to_the_logger_is_ignored(tmp_path: Path) -> None:
    a = make(tmp_path)
    a.start()
    cmd = NAME.to_bytes(8, "little") + bytes([200])
    msg = J1939Msg(100.0, 0.0, 6, 65240, 0xF9, 255, cmd, True, False, False)
    assert a.on_message(msg) == ([], [])
    assert a.current == 247


def test_NP_7_after_cannot_claim_answers_requests_with_cannot_claim(tmp_path: Path) -> None:
    a = make(tmp_path)
    a.start()
    a.on_message(claim(ENGINE, 247))
    a.on_message(claim(ENGINE + 1, 246))
    sends, _ = a.on_message(request(PGN_CLAIM, 0xF9, 255))
    assert [(r.pgn, sa) for r, sa in sends] == [(PGN_CLAIM, NULL_SA)]


def test_DET_4_own_claims_are_not_contests(tmp_path: Path) -> None:
    a = make(tmp_path)
    a.start()
    own = J1939Msg(
        100.0, 0.0, 6, PGN_CLAIM, 247, 255, NAME.to_bytes(8, "little"), False, True, False
    )
    assert a.on_message(own) == ([], [])
    assert a.current == 247
