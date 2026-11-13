"""decode: ID split, NAME decode, transport reassembly, limits and counts."""

from __future__ import annotations

from j1939logger.decode import (
    PGN_ETP_CM,
    PGN_TP_CM,
    PGN_TP_DT,
    TP_MAX_BYTES,
    decode,
    decode_name,
    new_state,
    split_id,
)
from j1939logger.types import Frame


def can_id(pgn: int, sa: int, da: int = 255, priority: int = 6) -> int:
    pf = (pgn >> 8) & 0xFF
    ps = da if pf < 240 else pgn & 0xFF
    return (priority << 26) | ((pgn >> 16) << 24) | (pf << 16) | (ps << 8) | sa


def fr(
    cid: int,
    data: bytes,
    t: float = 0.0,
    *,
    extended: bool = True,
    remote: bool = False,
    error: bool = False,
    own: bool = False,
) -> Frame:
    return Frame(
        ts_kernel=1_793_975_490.0 + t,
        ts_mono=100.0 + t,
        can_id=cid,
        extended=extended,
        remote=remote,
        error=error,
        data=data,
        own=own,
    )


def rts(sa: int, da: int, pgn: int, size: int, t: float = 0.0) -> Frame:
    packets = min((size + 6) // 7, 255)
    body = bytes([16, size & 0xFF, size >> 8, packets, 0xFF]) + pgn.to_bytes(3, "little")
    return fr(can_id(PGN_TP_CM, sa, da, 7), body, t)


def bam(sa: int, pgn: int, size: int, t: float = 0.0, packets: int = -1) -> Frame:
    n = min((size + 6) // 7, 255) if packets < 0 else packets
    body = bytes([32, size & 0xFF, size >> 8, n, 0xFF]) + pgn.to_bytes(3, "little")
    return fr(can_id(PGN_TP_CM, sa, 255, 7), body, t)


def cts(receiver: int, sender: int, count: int, next_seq: int, pgn: int, t: float) -> Frame:
    body = bytes([17, count, next_seq, 0xFF, 0xFF]) + pgn.to_bytes(3, "little")
    return fr(can_id(PGN_TP_CM, receiver, sender, 7), body, t)


def dts(sa: int, da: int, payload: bytes, t0: float, gap: float = 0.05) -> list[Frame]:
    out = []
    chunks = [payload[i : i + 7] for i in range(0, len(payload), 7)]
    for i, chunk in enumerate(chunks):
        body = bytes([i + 1]) + chunk + b"\xff" * (7 - len(chunk))
        out.append(fr(can_id(PGN_TP_DT, sa, da, 7), body, t0 + gap * (i + 1)))
    return out


# -- ID split and NAME -----------------------------------------------------


def test_IDN_1_split_id_pdu2_broadcast() -> None:
    assert split_id(0x0CF00400) == (3, 61444, 0x00, 255)  # EEC1 from the engine


def test_IDN_1_split_id_pdu1_destination_specific() -> None:
    assert split_id(0x18EA00F9) == (6, 59904, 0xF9, 0x00)  # request from SA 249 to 0
    assert split_id(0x18EAFFFE) == (6, 59904, 0xFE, 255)


def test_IDN_1_split_id_data_page() -> None:
    assert split_id(0x19F00400) == (6, 0x1F004, 0x00, 255)


def test_IDN_1_decode_logger_name() -> None:
    n = decode_name(0x9FFEFFFFFFE00001)
    assert (n.aac, n.industry_group, n.vs_instance, n.vehicle_system) == (1, 1, 15, 127)
    assert (n.function, n.function_instance, n.ecu_instance) == (255, 31, 7)
    assert (n.mfr_code, n.identity) == (2047, 1)


def test_IDN_1_decode_session_142_scan_tool_name() -> None:
    n = decode_name(0x8000810033A1B2C4)
    assert (n.aac, n.industry_group, n.function, n.mfr_code, n.identity) == (
        1,
        0,
        129,
        413,
        0x1B2C4,
    )


def test_IDN_1_address_claim_becomes_a_message_with_its_name_bytes() -> None:
    name = 0x8000810033A1B2C4
    claim = fr(can_id(60928, 249, 255), name.to_bytes(8, "little"))
    msgs, _, _, _ = decode([claim], new_state(32))
    assert len(msgs) == 1
    m = msgs[0]
    assert (m.pgn, m.sa, m.da, m.via_tp) == (60928, 249, 255, False)
    assert decode_name(int.from_bytes(m.data, "little")).function == 129


# -- own traffic and replies to the logger (NP-15) ---------------------------


def test_NP_15_own_frames_and_replies_to_logger_are_marked() -> None:
    own = fr(can_id(59904, 247, 0), b"\xec\xfe\x00", own=True)
    reply = fr(can_id(59392, 0, 247), bytes(8))
    other = fr(can_id(59392, 0, 249), bytes(8))
    msgs, _, _, _ = decode([own, reply, other], new_state(32), logger_sa=247)
    assert [m.own for m in msgs] == [True, False, False]
    assert [m.reply_to_logger for m in msgs] == [False, True, False]


# -- frames that aren't J1939 (DET-19) --------------------------------------


def test_DET_19_standard_remote_and_error_frames_are_counted_never_decoded() -> None:
    frames = [
        fr(0x123, b"\x01", extended=False),
        fr(0x18FEF100, b"", remote=True),
        fr(0x20000004, bytes(8), error=True),
        fr(0x0CF00400, bytes(8)),
    ]
    msgs, stats, _, _ = decode(frames, new_state(32))
    assert [m.pgn for m in msgs] == [61444]
    assert stats.non_j1939 == {"standard": 1, "remote": 1, "error": 1}


def test_DET_19_wrong_length_claim_and_request_are_counted_malformed() -> None:
    frames = [fr(can_id(60928, 9, 255), bytes(7)), fr(can_id(59904, 9, 0), bytes(2))]
    msgs, stats, _, _ = decode(frames, new_state(32))
    assert msgs == []
    assert stats.malformed == {"claim_length": 1, "request_length": 1}


def test_DET_19_stats_are_cumulative_across_batches() -> None:
    state = new_state(32)
    decode([fr(0x1, b"", extended=False)], state)
    _, stats, _, _ = decode([fr(0x2, b"", extended=False)], state)
    assert stats.non_j1939["standard"] == 2


# -- transport protocol ------------------------------------------------------


def test_DET_19_bam_is_reassembled_with_the_time_of_the_bam() -> None:
    payload = bytes(range(20))
    frames = [bam(0x00, 65260, len(payload), t=0.0), *dts(0x00, 255, payload, 0.0)]
    msgs, stats, tx, _ = decode(frames, new_state(32))
    assert len(msgs) == 1
    m = msgs[0]
    assert (m.pgn, m.sa, m.da, m.via_tp, m.data) == (65260, 0, 255, True, payload)
    assert m.ts_mono == 100.0
    assert stats.tp_closed == {"completed": 1}
    assert tx == []


def test_DET_19_rts_cts_transfer_is_reassembled() -> None:
    payload = bytes(range(30))
    frames = [
        rts(0xF9, 0x00, 54272, len(payload), 0.0),
        cts(0x00, 0xF9, 5, 1, 54272, 0.1),
        *dts(0xF9, 0x00, payload, 0.1),
    ]
    msgs, stats, _, _ = decode(frames, new_state(32))
    assert [(m.pgn, m.sa, m.da, m.data) for m in msgs] == [(54272, 0xF9, 0x00, payload)]
    assert stats.tp_closed == {"completed": 1}


def test_DET_19_1785_bytes_accepted_1786_rejected() -> None:
    payload = bytes(i % 256 for i in range(TP_MAX_BYTES))
    ok = [bam(0x00, 65242, TP_MAX_BYTES), *dts(0x00, 255, payload, 0.0, gap=0.01)]
    msgs, _, _, _ = decode(ok, new_state(32))
    assert len(msgs) == 1 and len(msgs[0].data) == TP_MAX_BYTES
    _, stats, _, _ = decode([bam(0x00, 65242, TP_MAX_BYTES + 1)], new_state(32))
    assert stats.tp_closed == {"oversize": 1}


def test_NP_9_oversize_rts_to_logger_gets_connection_abort() -> None:
    _, _, tx, _ = decode([rts(0x00, 247, 65259, 1786)], new_state(32), logger_sa=247)
    assert len(tx) == 1
    abort = tx[0]
    assert (abort.pgn, abort.da, abort.kind) == (PGN_TP_CM, 0x00, "protocol")
    assert abort.data[0] == 255 and abort.data[1] == 9
    assert int.from_bytes(abort.data[5:8], "little") == 65259


def test_DET_19_rejected_transfer_between_others_sends_nothing() -> None:
    _, _, tx, _ = decode([rts(0x00, 0x03, 65259, 1786)], new_state(32), logger_sa=247)
    assert tx == []


def test_DET_19_open_transfers_never_exceed_tp_sessions() -> None:
    frames = [bam(sa, 65260, 20, t=sa * 0.001) for sa in range(5)]
    _, stats, _, state = decode(frames, new_state(3))
    assert len(state.transfers) == 3
    assert stats.tp_closed == {"too_many_sessions": 2}


def test_DET_19_duplicate_and_out_of_order_packets_close_the_transfer() -> None:
    payload = bytes(range(21))
    pk = dts(0x00, 255, payload, 0.0)
    _, s1, _, _ = decode([bam(0x00, 65260, 21), pk[0], pk[0]], new_state(32))
    assert s1.tp_closed == {"duplicate": 1}
    _, s2, _, _ = decode([bam(0x00, 65260, 21), pk[0], pk[2]], new_state(32))
    assert s2.tp_closed == {"bad_sequence": 1}


def test_DET_19_t1_timeout_between_packets() -> None:
    payload = bytes(range(21))
    pk = dts(0x00, 255, payload, 0.0)
    late = [fr(f.can_id, f.data, t=0.05 + 0.8) for f in pk[1:2]]
    msgs, stats, _, _ = decode([bam(0x00, 65260, 21), pk[0], *late], new_state(32))
    assert msgs == []
    assert stats.tp_closed == {"timeout_t1": 1}
    assert stats.malformed == {"tp_dt_no_session": 1}


def test_DET_19_t3_timeout_when_no_cts_follows_rts() -> None:
    frames = [rts(0xF9, 0x00, 54272, 30, 0.0), fr(0x0CF00400, bytes(8), t=1.3)]
    _, stats, _, _ = decode(frames, new_state(32))
    assert stats.tp_closed == {"timeout_t3": 1}


def test_DET_19_t2_and_t4_timeouts_after_cts() -> None:
    f = [rts(0xF9, 0x00, 54272, 30), cts(0x00, 0xF9, 5, 1, 54272, 0.1)]
    _, s2, _, _ = decode([*f, fr(0x0CF00400, bytes(8), t=0.1 + 1.3)], new_state(32))
    assert s2.tp_closed == {"timeout_t2": 1}
    hold = [rts(0xF9, 0x00, 54272, 30), cts(0x00, 0xF9, 0, 1, 54272, 0.1)]
    _, s4, _, _ = decode([*hold, fr(0x0CF00400, bytes(8), t=0.1 + 1.1)], new_state(32))
    assert s4.tp_closed == {"timeout_t4": 1}


def test_DET_19_connection_abort_closes_the_transfer() -> None:
    body = bytes([255, 1, 0xFF, 0xFF, 0xFF]) + (54272).to_bytes(3, "little")
    frames = [rts(0xF9, 0x00, 54272, 30), fr(can_id(PGN_TP_CM, 0x00, 0xF9, 7), body, 0.1)]
    _, stats, _, state = decode(frames, new_state(32))
    assert stats.tp_closed == {"aborted": 1}
    assert state.transfers == {}


def test_DET_19_new_bam_from_same_sender_replaces_the_open_one() -> None:
    _, stats, _, state = decode([bam(0x00, 65260, 20), bam(0x00, 65259, 30, t=0.1)], new_state(32))
    assert stats.tp_closed == {"replaced": 1}
    assert len(state.transfers) == 1


def test_DET_19_tp_size_and_packet_count_must_agree() -> None:
    _, stats, _, state = decode([bam(0x00, 65260, 20, packets=9)], new_state(32))
    assert stats.malformed == {"tp_size": 1}
    assert state.transfers == {}


# -- extended transport protocol (DET-10) ------------------------------------


def test_DET_10_etp_is_recognized_and_counted_not_reassembled() -> None:
    etp_rts = bytes([20, 0x00, 0x10, 0x00, 0x00]) + (55552).to_bytes(3, "little")
    msgs, stats, _, state = decode([fr(can_id(PGN_ETP_CM, 0xF9, 0x00, 7), etp_rts)], new_state(32))
    assert stats.etp_seen == 1
    assert [m.pgn for m in msgs] == [PGN_ETP_CM]
    assert state.transfers == {}
