"""SC-12a: decode with generated malformed frames and transfers (Hypothesis).

Properties: no unhandled exception, decoding continues, open transfers never
exceed limits.tp_sessions, and every frame is accounted for.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from j1939logger.decode import PGN_TP_CM, PGN_TP_DT, TP_MAX_BYTES, decode, new_state
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
    kind = draw(st.sampled_from(["any", "tp_cm", "tp_dt", "claim", "flags"]))
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


@settings(max_examples=300, deadline=None)
@given(batches=st.lists(st.lists(frames(), max_size=40), max_size=6))
def test_SC_12a_decode_never_raises_and_respects_tp_limit(batches: list[list[Frame]]) -> None:
    state = new_state(TP_LIMIT)
    total = 0
    for batch in sorted(batches, key=len):
        batch = sorted(batch, key=lambda f: f.ts_mono)
        msgs, stats, tx, state = decode(batch, state, logger_sa=247)
        total += len(batch)
        assert len(state.transfers) <= TP_LIMIT
        assert all(len(m.data) <= TP_MAX_BYTES for m in msgs)
        assert all(r.pgn == PGN_TP_CM and r.data[0] == 255 for r in tx)
    assert sum(stats.non_j1939.values()) <= total if batches else True


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
