"""decode v2 (DC-12): CTS and EOMA for transfers to the logger; bus state from error frames."""

from __future__ import annotations

from j1939logger.decode import PGN_TP_CM, PGN_TP_DT, bus_state, decode, new_state
from j1939logger.types import Frame

LOGGER = 247


def can_id(pgn: int, sa: int, da: int = 255, priority: int = 7) -> int:
    pf = (pgn >> 8) & 0xFF
    ps = da if pf < 240 else pgn & 0xFF
    return (priority << 26) | (pf << 16) | (ps << 8) | sa


def fr(cid: int, data: bytes, t: float, error: bool = False) -> Frame:
    return Frame(1.7e9 + t, 100.0 + t, cid, not error, False, error, data, False)


def rts(sa: int, da: int, pgn: int, size: int, max_per_cts: int = 0xFF) -> Frame:
    packets = (size + 6) // 7
    body = bytes([16, size & 0xFF, size >> 8, packets, max_per_cts]) + pgn.to_bytes(3, "little")
    return fr(can_id(PGN_TP_CM, sa, da), body, 0.0)


def dt(sa: int, da: int, seq: int, chunk: bytes, t: float) -> Frame:
    return fr(can_id(PGN_TP_DT, sa, da), bytes([seq]) + chunk.ljust(7, b"\xff"), t)


def test_NP_9_rts_to_the_logger_gets_cts_then_eoma(tmp_path: object) -> None:
    payload = b"ENG*CM2350*SN 79512*"  # 20 bytes: 3 packets
    state = new_state(32)
    _, _, tx1, state = decode([rts(0x00, LOGGER, 65259, len(payload))], state, logger_sa=LOGGER)
    [cts] = tx1
    assert (cts.pgn, cts.da, cts.kind) == (PGN_TP_CM, 0x00, "protocol")
    assert cts.data[:3] == bytes([17, 3, 1])  # CTS for all 3 packets from packet 1
    frames = [dt(0x00, LOGGER, i + 1, payload[i * 7 : i * 7 + 7], 0.05 * (i + 1)) for i in range(3)]
    msgs, _, tx2, _ = decode(frames, state, logger_sa=LOGGER)
    assert [m.data for m in msgs] == [payload] and msgs[0].reply_to_logger
    [eoma] = tx2
    assert eoma.data[:5] == bytes([19, 20, 0, 3, 0xFF]) and eoma.da == 0x00


def test_NP_9_logger_asks_for_each_window_when_rts_limits_packets_per_cts(tmp_path: object) -> None:
    payload = bytes(range(30))  # 5 packets, 2 per CTS
    state = new_state(32)
    _, _, tx, state = decode([rts(0x03, LOGGER, 65242, 30, max_per_cts=2)], state, logger_sa=LOGGER)
    assert tx[0].data[1:3] == bytes([2, 1])
    windows = []
    for seq in range(1, 6):
        _, _, tx, state = decode(
            [dt(0x03, LOGGER, seq, payload[(seq - 1) * 7 : seq * 7], 0.05 * seq)],
            state,
            logger_sa=LOGGER,
        )
        windows += [(r.data[0], r.data[1], r.data[2]) for r in tx]
    assert windows == [(17, 2, 3), (17, 1, 5), (19, 30, 0)]


def test_NP_9_transfers_between_other_nodes_get_no_replies(tmp_path: object) -> None:
    _, _, tx, _ = decode([rts(0x00, 0x03, 65259, 20)], new_state(32), logger_sa=LOGGER)
    assert tx == []


def test_NP_3_bus_state_reads_bus_off_and_tx_error_passive() -> None:
    assert bus_state(fr(0x40, bytes(8), 0.0, error=True)) == "bus_off"
    passive = bytes([0, 0x20, 0, 0, 0, 0, 0, 0])
    assert bus_state(fr(0x04, passive, 0.0, error=True)) == "error_passive"
    rx_passive = bytes([0, 0x10, 0, 0, 0, 0, 0, 0])
    assert bus_state(fr(0x04, rx_passive, 0.0, error=True)) is None
    assert bus_state(fr(0x0CF00400, bytes(8), 0.0)) is None


def _nack(sa: int, requester: int, pgn: int) -> Frame:
    data = bytes([1, 0xFF, 0xFF, 0xFF, requester]) + pgn.to_bytes(3, "little")
    return fr(can_id(59392, sa, 255, 6), data, 0.0)


def test_NP_15_ack_naming_the_logger_is_a_reply_to_it() -> None:
    [msg], _, _, _ = decode([_nack(3, LOGGER, 65260)], new_state(4), LOGGER)
    assert (msg.pgn, msg.da, msg.reply_to_logger) == (59392, 255, True)  # DC-16


def test_NP_15_ack_naming_another_address_is_not() -> None:
    [msg], _, _, _ = decode([_nack(3, 249, 65260)], new_state(4), LOGGER)
    assert not msg.reply_to_logger
    [early], _, _, _ = decode([_nack(3, LOGGER, 65260)], new_state(4), None)
    assert not early.reply_to_logger  # no address yet
