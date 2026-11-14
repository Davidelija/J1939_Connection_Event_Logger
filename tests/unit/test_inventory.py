"""inventory (step 6 PR 1, DC-20): training, conditions, versions, approvals, removals."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from j1939logger.config import Inventory, validate_inventory
from j1939logger.inventory import (
    InventoryRefused,
    Training,
    approve,
    condition,
    confirm_record,
    next_entry_id,
    next_version,
    rejection_record,
    remove,
)
from j1939logger.session import settings_from_config
from j1939logger.types import J1939Msg

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
LOGGER = 0x9FFEFFFFFFE00001
ENGINE = 0x000000002E412A10  # E01 at SA 0 in inv-v2
TRANS = 0x000003001D20B4F1  # E02 at SA 3
NEW_ECU = 0x0000110012345678
LABELS = ["key-on engine off", "idle", "driving", "PTO"]
NOW = "2026-11-14T10:00:00.000Z"


def settings(**over: Any) -> dict[str, Any]:
    s = settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))
    s.update(over)
    return s


def inv_v2() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8"))
    return data


def msg(pgn: int, sa: int, data: bytes = bytes(8), t: float = 100.0, own: bool = False) -> J1939Msg:
    return J1939Msg(t, 0.0, 6, pgn, sa, 255, data, False, own, False)


def claim(name: int, sa: int, t: float = 100.0, own: bool = False) -> J1939Msg:
    return msg(60928, sa, name.to_bytes(8, "little"), t, own)


def eec1(rpm: float, t: float = 100.0) -> J1939Msg:
    raw = int(rpm / 0.125)
    return msg(61444, 0, bytes([0xFF, 0x7D, 0x7D]) + raw.to_bytes(2, "little") + bytes(3), t)


def ccvs(kmh: float, t: float = 100.0) -> J1939Msg:
    raw = int(kmh * 256)
    return msg(65265, 0, bytes([0xFF]) + raw.to_bytes(2, "little") + bytes(5), t)


def pto1(rpm: float, t: float = 100.0) -> J1939Msg:
    raw = int(rpm / 0.125)
    return msg(65264, 0, bytes([0xFF]) + raw.to_bytes(2, "little") + bytes(5), t)


def training(**over: Any) -> Training:
    return Training(settings(**over), 100.0, LOGGER, "jdoe")


def proposal(t: Training, previous: Any = None, stored: Any = ()) -> dict[str, Any]:
    return t.propose(previous=previous, stored=stored, version="inv-v3", vin="1XKYD49X0GJ123456",
                     session=150, now_utc=NOW)  # fmt: skip


# -- TRN-12: conditions ------------------------------------------------------------


@pytest.mark.parametrize(
    ("rpm", "kmh", "pto", "label"),
    [
        (None, None, False, "key-on engine off"),
        (250.0, 0.0, False, "key-on engine off"),
        (650.0, 0.0, False, "idle"),
        (650.0, 4.9, False, "idle"),
        (1400.0, 55.0, False, "driving"),
        (900.0, 0.0, True, "PTO"),
    ],
)
def test_TRN_12_condition_from_engine_speed_vehicle_speed_and_pto(
    rpm: Any, kmh: Any, pto: bool, label: str
) -> None:
    assert condition(rpm, kmh, pto, LABELS, 400, 5) == label


def test_TRN_12_training_reports_conditions_and_pgns_per_ecu_in_each() -> None:
    t = training()
    t.observe(claim(ENGINE, 0))
    t.observe(msg(65262, 0))  # engine off
    t.observe(eec1(700))
    t.observe(msg(65270, 0))  # idle
    t.observe(ccvs(60))
    t.observe(msg(65265, 0))  # driving (CCVS itself)
    t.observe(pto1(1000))
    cov = t.coverage()
    assert cov["conditions"] == ["key-on engine off", "idle", "driving", "PTO"]
    assert cov["missing"] == []
    [ecu] = cov["pgns_per_ecu"]
    assert ecu["name"] == "0x000000002E412A10" and ecu["addresses"] == [0]
    assert ecu["pgns"]["key-on engine off"] == [65262]
    assert 65270 in ecu["pgns"]["idle"] and 65265 in ecu["pgns"]["driving"]


def test_TRN_12_pto_declared_by_the_operator() -> None:
    t = training()
    t.observe(claim(ENGINE, 0))
    assert t.coverage()["missing"] == ["idle", "driving", "PTO"]
    assert "PTO" in t.coverage(pto_declared=True)["conditions"]
    p = t.propose(previous=None, stored=(), version="inv-v1", vin=None, session=1, now_utc=NOW,
                  pto_declared=True)  # fmt: skip
    assert "PTO" in p["entries"][0]["states_seen"]


# -- TRN-2, TRN-3, TRN-7: training and the proposal ------------------------------------


def test_TRN_7_proposed_entries_hold_the_inventory_fields() -> None:
    t = training()
    for m in (claim(ENGINE, 0), msg(61444, 0), msg(65262, 0), claim(NEW_ECU, 17), msg(65132, 17)):
        t.observe(m)
    t.identity(17, 65259, "reply", b"Delta*TCU-9*SN 5*")
    p = proposal(t, previous=inv_v2(), stored=[inv_v2()])
    by_name = {e["name"]: e for e in p["entries"]}
    engine = by_name["0x000000002E412A10"]
    assert engine["entry"] == "E01"  # a NAME already in the inventory keeps its entry ID
    assert engine["pgns_sent"] == [61444, 65262] and engine["category"] == "vehicle ECU in baseline"
    assert engine["pgns_approved"] == inv_v2()["entries"][0]["pgns_approved"]  # approvals kept
    new = by_name["0x0000110012345678"]
    assert new["entry"] == "E05"  # after E04, the highest stored
    assert new["make"] == "Delta" and new["self_reported"]["component_id"] == "Delta*TCU-9*SN 5"
    assert new["name_fields"]["function"] == 0x11 and new["added"]["how"] == "training"
    assert by_name["0x8000FE003C04D2E8"]["category"] == "external device (approved)"  # E04 stays
    assert (p["previous"], p["source_session"], p["operator"]) == ("inv-v2", 150, "jdoe")
    assert p["vehicle"]["model"] == "T680"  # copied from the previous inventory
    assert isinstance(validate_inventory(p), Inventory)  # a valid inv-1 file


def test_TRN_2_device_that_never_claims_and_one_that_claims_late() -> None:
    t = training()
    t.observe(msg(65000, 40))  # never claims
    t.observe(msg(65001, 41))
    t.observe(claim(NEW_ECU, 41))  # claims after sending: one entry
    p = proposal(t)
    names = sorted((e["name"] or "", tuple(e["addresses"])) for e in p["entries"])
    assert names == [("", (40,)), ("0x0000110012345678", (41,))]
    late = next(e for e in p["entries"] if e["name"])
    assert late["pgns_sent"] == [65001]


def test_TRN_14_the_logger_is_never_part_of_the_inventory() -> None:
    t = training()
    t.observe(claim(LOGGER, 247))  # its own NAME, even when not marked own
    t.observe(msg(59904, 247, b"\x00\xee\x00", own=True))
    assert proposal(t)["entries"] == []


def test_TRN_3_training_stops_observing_at_the_timeout() -> None:
    t = training(**{"training.timeout_min": 1})
    t.observe(claim(ENGINE, 0, t=100.0))
    assert t.observing(159.0)
    t.observe(msg(65262, 0, t=161.0))  # after 60 s: not recorded
    assert t.timed_out and not t.observing(200.0)
    assert proposal(t)["entries"][0]["pgns_sent"] == []


def test_TRN_11_training_and_approvals_never_change_the_inventory_they_read() -> None:
    before = inv_v2()
    frozen = copy.deepcopy(before)
    t = training()
    t.observe(claim(NEW_ECU, 17))
    proposal(t, previous=before, stored=[before])
    event = {"type": "known_device_new_pgn", "sa": 0, "entry": "E01", "pgn": 65132,
             "direction": "sent"}  # fmt: skip
    approve(before, event, event_id="150-7", version="inv-v3", operator="jdoe", reason="r",
            session=150, now_utc=NOW)  # fmt: skip
    assert before == frozen


# -- TRN-6: versions and entry IDs -----------------------------------------------------


def test_TRN_6_versions_and_entry_ids_are_never_reused() -> None:
    assert next_version([1, 2]) == "inv-v3" and next_version([]) == "inv-v1"
    v2 = inv_v2()
    v3, _ = remove(v2, "E04", version="inv-v3", operator="jdoe", reason="sold", session=150,
                   now_utc=NOW)  # fmt: skip
    assert next_entry_id([v3]) == 4  # alone, v3 would hand out E04 again
    assert next_entry_id([v2, v3]) == 5  # across the stored versions it does not


# -- TRN-4: confirm or reject ----------------------------------------------------------


def test_TRN_4_confirm_and_reject_records() -> None:
    t = training()
    t.observe(claim(ENGINE, 0))
    p = proposal(t)
    ok = confirm_record(p, "jdoe", None)
    assert (ok.type, ok.sev, ok.fields["kind"], ok.fields["new_inventory"]) == (
        "approval", "notice", "inventory", "inv-v3",
    )  # fmt: skip
    assert ok.fields["entries"] == [p["entries"][0]["entry"]]
    no = rejection_record(p, "jdoe", "ELD was plugged in")
    assert (no.type, no.fields["proposed_inventory"]) == ("rejection", "inv-v3")


# -- TRN-5, TRN-10: approvals ----------------------------------------------------------


def approve_v2(event: dict[str, Any], **kw: Any) -> tuple[dict[str, Any], Any]:
    args: dict[str, Any] = {"event_id": "150-5", "version": "inv-v3", "operator": "jdoe",
                            "reason": "RO 6001", "session": 150, "now_utc": NOW,
                            "stored": [inv_v2()]}  # fmt: skip
    args.update(kw)
    return approve(inv_v2(), event, **args)


def test_TRN_5_approving_a_logged_device_adds_an_approved_entry() -> None:
    start = {"type": "connection_start", "sa": 249, "name": "0x8000810033A1B2C4",
             "name_fields": {"function": 129}}  # fmt: skip
    asked = ["65260 VIN -> SA 0", "65226 DM1 -> global", "65260 VIN -> SA 3"]
    end = {"type": "connection_end", "pgns_sent": [{"pgn": 59904}, {"pgn": 60928}],
           "requests_first_100": asked}  # fmt: skip
    v3, rec = approve_v2(start, end=end)
    new = v3["entries"][-1]
    assert (new["entry"], new["category"], new["addresses"]) == (
        "E05", "external device (approved)", [249],
    )  # fmt: skip
    assert new["pgns_sent"] == [59904, 60928] and new["requests_trained"] == [65226, 65260]
    assert new["added"]["from_event"] == "150-5"
    assert (rec.type, rec.fields["kind"], rec.fields["entries"]) == ("approval", "device", ["E05"])
    assert rec.fields["events_cleared"] == ["150-5"]
    assert isinstance(validate_inventory(v3), Inventory)
    with pytest.raises(InventoryRefused):
        approve(v3, start, event_id="150-5", version="inv-v4", operator="jdoe", reason="again",
                session=150, now_utc=NOW)  # fmt: skip


def test_TRN_10_approving_a_new_pgn_adds_it_to_the_approved_list() -> None:
    event = {"type": "known_device_new_pgn", "sa": 0, "entry": "E01", "pgn": 0,
             "direction": "sent"}  # fmt: skip
    v3, rec = approve_v2(event, warning_shown=True, control_pgns=[0, 256])
    e01 = v3["entries"][0]
    assert {"pgn": 0, "kind": "PGN sent", "reason": "RO 6001", "utc": NOW, "operator": "jdoe",
            "from_event": "150-5"} in e01["pgns_approved"]  # fmt: skip
    assert e01["pgns_sent"] == inv_v2()["entries"][0]["pgns_sent"]  # trained PGNs kept apart
    assert (rec.fields["kind"], rec.fields["pgn"], rec.fields["control_warning_shown"]) == (
        "PGN sent", 0, True,
    )  # fmt: skip
    requested = {"type": "known_device_new_pgn", "sa": 238, "entry": "E04", "pgn": 65227,
                 "direction": "requested"}  # fmt: skip
    _, rec2 = approve_v2(requested)
    assert rec2.fields["kind"] == "PGN requested" and rec2.fields["control_warning_shown"] is False


def test_TRN_10_approving_a_notice_address_change_adds_the_address() -> None:
    event = {"type": "address_change", "sev": "notice", "entry": "E02", "new_sa": 11}
    v3, rec = approve_v2(event)
    assert v3["entries"][1]["addresses"] == [3, 11] and rec.fields["kind"] == "address"
    with pytest.raises(InventoryRefused):
        approve_v2({**event, "sev": "info"})


def test_TRN_10_other_records_are_refused() -> None:
    with pytest.raises(InventoryRefused, match="cannot be approved"):
        approve_v2({"type": "sweep"})


# -- TRN-14, TRN-15: removals ----------------------------------------------------------


def test_TRN_14_removing_a_device_retires_its_entry() -> None:
    v3, rec = remove(inv_v2(), "E02", version="inv-v3", operator="jdoe", reason="replaced",
                     session=150, now_utc=NOW, warning_shown=True)  # fmt: skip
    assert [e["entry"] for e in v3["entries"]] == ["E01", "E03", "E04"]
    assert rec.type == "inventory_remove" and rec.fields == {
        "operator": "jdoe", "entry": "E02", "name": "0x000003001D20B4F1",
        "removed": "remove device", "pgn": None, "reason": "replaced", "warning_shown": True,
        "old_inventory": "inv-v2", "new_inventory": "inv-v3",
    }  # fmt: skip
    with pytest.raises(InventoryRefused):
        remove(inv_v2(), "E02", version="inv-v3", operator="jdoe", reason="", session=150,
               now_utc=NOW)  # fmt: skip


def test_TRN_15_removing_one_pgn_sent_or_requested() -> None:
    v3, rec = remove(inv_v2(), "E01", pgn=65226, direction="sent", version="inv-v3",
                     operator="jdoe", reason="not here", session=150, now_utc=NOW)  # fmt: skip
    assert 65226 not in v3["entries"][0]["pgns_sent"]
    assert rec.fields["removed"] == "remove PGN sent"
    v3b, _ = remove(inv_v2(), "E01", pgn=64892, direction="sent", version="inv-v3",
                    operator="jdoe", reason="regen done", session=150, now_utc=NOW)  # fmt: skip
    assert v3b["entries"][0]["pgns_approved"] == []  # the approved PGN
    v3c, rec3 = remove(inv_v2(), "E04", pgn=65260, direction="requested", version="inv-v3",
                       operator="jdoe", reason="r", session=150, now_utc=NOW)  # fmt: skip
    assert 65260 not in v3c["entries"][3]["requests_trained"]
    assert rec3.fields["removed"] == "remove PGN requested"
    with pytest.raises(InventoryRefused):
        remove(inv_v2(), "E01", pgn=1, direction="sent", version="inv-v3", operator="jdoe",
               reason="r", session=150, now_utc=NOW)  # fmt: skip
