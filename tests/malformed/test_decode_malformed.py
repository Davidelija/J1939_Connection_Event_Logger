"""SC-12a: decode with generated malformed frames and transfers (Hypothesis).

Properties: no unhandled exception, decoding continues, open transfers never
exceed limits.tp_sessions, and the per-frame counts (non-J1939 frames, over-long
frames, the reserved data page, wrong-length claims and requests, ETP RTS) equal
exactly what was sent. Extended transport protocol frames (ETP.CM 51200, ETP.DT
50944) are generated with bad lengths and out-of-order packets (DET-10).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from j1939logger.decode import (
    PGN_ETP_CM,
    PGN_ETP_DT,
    PGN_TP_CM,
    PGN_TP_DT,
    TP_MAX_BYTES,
    DecodeStats,
    decode,
    new_state,
    split_id,
)
from j1939logger.types import Frame

TP_LIMIT = 4


def _id(pgn: int, sa: int, da: int) -> int:
    pf = (pgn >> 8) & 0xFF
    ps = da if pf < 240 else pgn & 0xFF
    return (7 << 26) | (pf << 16) | (ps << 8) | sa


addresses = st.sampled_from([0x00, 0x03, 0xF9, 0xFE, 247, 255])


@st.composite
def frames(draw: st.DrawFn) -> Frame:
    t = draw(st.floats(min_value=0, max_value=5, allow_nan=False))
    kind = draw(st.sampled_from(["any", "tp_cm", "tp_dt", "etp_cm", "etp_dt", "claim", "flags"]))
    sa, da = draw(addresses), draw(addresses)
    data = draw(st.binary(min_size=0, max_size=10))  # lengths over 8 are malformed
    if kind == "any":
        cid = draw(st.integers(min_value=0, max_value=0x1FFFFFFF))
    elif kind == "tp_cm":
        cid = _id(PGN_TP_CM, sa, da)
        control = draw(st.sampled_from([16, 17, 19, 32, 255, 0, 99]))
        size = draw(st.integers(min_value=0, max_value=TP_MAX_BYTES + 300))
        packets = draw(st.integers(min_value=0, max_value=255))
        pgn = draw(st.integers(min_value=0, max_value=0x3FFFF))
        data = bytes([control, size & 0xFF, (size >> 8) & 0xFF, packets, 0xFF])
        data += pgn.to_bytes(3, "little")
        data = data[: draw(st.integers(min_value=0, max_value=8))]
    elif kind == "tp_dt":
        cid = _id(PGN_TP_DT, sa, da)
        seq = draw(st.integers(min_value=0, max_value=255))
        data = bytes([seq]) + draw(st.binary(min_size=0, max_size=7))
    elif kind == "etp_cm":  # RTS, CTS, DPO, EOMA, Abort and unknown controls; bad lengths
        cid = _id(PGN_ETP_CM, sa, da)
        control = draw(st.sampled_from([20, 21, 22, 23, 255, 0, 99]))
        size = draw(st.integers(min_value=0, max_value=0xFFFFFFFF))
        pgn = draw(st.integers(min_value=0, max_value=0x3FFFF))
        data = bytes([control]) + size.to_bytes(4, "little") + pgn.to_bytes(3, "little")
        data = data[: draw(st.integers(min_value=0, max_value=10))]  # 9 and 10 are malformed
    elif kind == "etp_dt":  # sequence numbers in any order, any length
        cid = _id(PGN_ETP_DT, sa, da)
        seq = draw(st.integers(min_value=0, max_value=255))
        data = bytes([seq]) + draw(st.binary(min_size=0, max_size=9))
    elif kind == "claim":
        cid = _id(60928, sa, 255)  # bad and all-zero NAMEs, wrong lengths
        data = draw(st.sampled_from([bytes(8), b"\xff" * 8, bytes(7), data]))
    else:
        cid = draw(st.integers(min_value=0, max_value=0x1FFFFFFF))
    return Frame(
        ts_kernel=1_793_975_490.0 + t,
        ts_mono=100.0 + t,
        can_id=cid,
        extended=draw(st.booleans()) if kind == "flags" else True,
        remote=draw(st.booleans()) if kind == "flags" else False,
        error=draw(st.booleans()) if kind == "flags" else False,
        data=data,
        own=False,
    )


def expected_counts(sent: list[Frame]) -> DecodeStats:
    """The counts decode must report for these frames, from the rules in its docstring.

    Only the per-frame counts: transport-protocol counts depend on open transfers
    and are checked by the limit properties instead.
    """
    want = DecodeStats()

    def add(table: dict[str, int], key: str) -> None:
        table[key] = table.get(key, 0) + 1

    for f in sent:
        if f.error:
            add(want.non_j1939, "error")
        elif f.remote:
            add(want.non_j1939, "remote")
        elif not f.extended:
            add(want.non_j1939, "standard")
        elif len(f.data) > 8:
            add(want.malformed, "dlc")
        else:
            _, pgn, _, _ = split_id(f.can_id)
            if pgn >> 16 == 0x3:
                add(want.malformed, "reserved_edp_dp")
            elif pgn in (PGN_TP_CM, PGN_TP_DT):
                continue
            else:
                if pgn == PGN_ETP_CM and f.data[:1] == bytes([20]):
                    want.etp_seen += 1
                if pgn == 60928 and len(f.data) != 8:
                    add(want.malformed, "claim_length")
                elif pgn == 59904 and len(f.data) not in (3, 8):
                    add(want.malformed, "request_length")
    return want


PER_FRAME = ("dlc", "reserved_edp_dp", "claim_length", "request_length")


def check_decode(batches: list[list[Frame]]) -> None:
    """The SC-12a properties for one run of batches (also used to replay regressions)."""
    state = new_state(TP_LIMIT)
    stats = DecodeStats()
    sent: list[Frame] = []
    for batch in sorted(batches, key=len):
        batch = sorted(batch, key=lambda f: f.ts_mono)
        msgs, stats, tx, state = decode(batch, state, logger_sa=247)
        sent += batch
        assert len(state.transfers) <= TP_LIMIT
        assert all(len(m.data) <= TP_MAX_BYTES for m in msgs)
        assert all(r.pgn == PGN_TP_CM and r.data[0] == 255 for r in tx)
    want = expected_counts(sent)
    assert stats.non_j1939 == want.non_j1939  # exactly what was sent, not just at most
    assert {k: v for k, v in stats.malformed.items() if k in PER_FRAME} == want.malformed
    assert stats.etp_seen == want.etp_seen


@settings(max_examples=300, deadline=None)
@given(batches=st.lists(st.lists(frames(), max_size=40), max_size=6))
def test_SC_12a_decode_never_raises_and_respects_tp_limit(batches: list[list[Frame]]) -> None:
    check_decode(batches)


# -- saved failing examples (test plan section 4): replayed in every CI run ------------------

REGRESSIONS = Path(__file__).resolve().parent / "regressions"


def load_regression(path: Path) -> list[list[Frame]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["target"] == "decode", f"{path.name}: unknown target {doc['target']!r}"
    assert doc.get("finding"), f"{path.name}: say what the example found"
    return [
        [
            Frame(
                1_793_975_490.0 + f["t"],
                100.0 + f["t"],
                int(f["can_id"], 16),
                f.get("extended", True),
                f.get("remote", False),
                f.get("error", False),
                bytes.fromhex(f["data"]),
                False,
            )
            for f in batch
        ]
        for batch in doc["batches"]
    ]


@pytest.mark.parametrize("path", sorted(REGRESSIONS.glob("*.json")), ids=lambda p: p.stem)
def test_SC_12a_saved_regressions_replay(path: Path) -> None:
    check_decode(load_regression(path))


def test_SC_12a_regressions_folder_is_replayed() -> None:
    assert sorted(REGRESSIONS.glob("*.json")), "tests/malformed/regressions/ has no examples"


def test_SC_12a_etp_frames_are_counted_and_passed_through_not_reassembled() -> None:
    def f(pgn: int, data: bytes, i: int) -> Frame:
        return Frame(1.0, 100.0 + i * 0.01, _id(pgn, 0xF9, 0x00), True, False, False, data, False)

    rts = bytes([20]) + (3000).to_bytes(4, "little") + (65260).to_bytes(3, "little")
    sent = [
        f(PGN_ETP_CM, rts, 0),  # RTS: counted
        f(PGN_ETP_DT, bytes([3]) + bytes(7), 1),  # out of order
        f(PGN_ETP_DT, bytes([1]) + bytes(7), 2),
        f(PGN_ETP_CM, rts[:3], 3),  # a short RTS still starts with 20: counted
        f(PGN_ETP_CM, bytes([21, 1]), 4),  # CTS, short
        f(PGN_ETP_DT, bytes(10), 5),  # over 8 bytes: malformed (dlc)
        f(PGN_ETP_CM, b"", 6),  # empty
    ]
    msgs, stats, tx, state = decode(sent, new_state(TP_LIMIT), logger_sa=247)
    assert stats.etp_seen == 2
    assert stats.malformed == {"dlc": 1}
    assert [m.pgn for m in msgs] == [PGN_ETP_CM, PGN_ETP_DT, PGN_ETP_DT, PGN_ETP_CM,
                                     PGN_ETP_CM, PGN_ETP_CM]  # fmt: skip
    assert state.transfers == {} and tx == []  # recognized, never reassembled (DET-10)


@settings(max_examples=200, deadline=None)
@given(n=st.integers(min_value=1, max_value=60))
def test_SC_12a_flood_of_new_transfers_stays_within_limit(n: int) -> None:
    # A flood of BAMs from many senders: at most TP_LIMIT open, the rest counted.
    state = new_state(TP_LIMIT)
    body = bytes([32, 20, 0, 3, 0xFF]) + (65260).to_bytes(3, "little")
    flood = [
        Frame(1.0, 100.0 + i * 0.001, _id(PGN_TP_CM, i % 254, 255), True, False, False, body, False)
        for i in range(n)
    ]
    _, stats, _, state = decode(flood, state)
    assert len(state.transfers) == min(n, TP_LIMIT)
    assert sum(stats.tp_closed.values()) == max(0, n - TP_LIMIT)
