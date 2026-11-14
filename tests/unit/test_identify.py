"""identify (step 5 PR 1, DC-17, DC-18): classification rules, library score, make, confidence."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from j1939logger.config import Library, validate_library
from j1939logger.decode import decode_name
from j1939logger.identify import (
    Identification,
    classify,
    identification_record,
    identify,
    reclassify,
    reply_text,
    severity,
)
from j1939logger.requests import RequestOutcome
from j1939logger.types import Connection, Name

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 31, 40, 118000, tzinfo=timezone.utc)
SCAN_TOOL = 0x8000810033A1B2C4  # function 129, mfr code 413
TIE = 0.1


def library() -> Library:
    lib = validate_library(json.loads((EXAMPLES / "lib-v1.json").read_text(encoding="utf-8")))
    assert isinstance(lib, Library)
    return lib


def with_codes(lib: Library, codes: dict[str, str]) -> Library:
    return Library(lib.version, lib.devices, codes)


def entry(type_: str, make: Optional[str] = None, model: Optional[str] = None,
          functions: tuple[int, ...] = (), typical: tuple[int, ...] = (),
          hints: tuple[int, ...] = (), never: tuple[int, ...] = ()) -> dict[str, Any]:  # fmt: skip
    return {"type": type_, "make": make, "model": model, "functions": list(functions),
            "sa_hints": list(hints), "requests_typical": list(typical),
            "sends_typical": [], "requests_never": list(never), "sends_never": []}  # fmt: skip


def conn(name: Optional[int] = SCAN_TOOL, sa: int = 249,
         category: str = "external device (unrecognized)") -> Connection:  # fmt: skip
    decoded = decode_name(name) if name is not None else None
    key = ("name", name) if name is not None else ("sa", sa)
    return Connection(2, key, sa, decoded, 100.0, 100.0, category)


def reply(pgn: int, text: bytes, t: float = 102.0) -> RequestOutcome:
    return RequestOutcome(2, pgn, 249, "reply", text, 1, t)


def none(pgn: int, outcome: str = "no reply", t: float = 102.0) -> RequestOutcome:
    return RequestOutcome(2, pgn, 249, outcome, None, 2 if outcome == "no reply" else 1, t)


EXAMPLE_OUTCOMES = [none(65259, t=102.002), reply(65242, b"\x01VDT 4.2.1*", t=104.502),
                    none(64965, "NACK", t=104.532)]  # fmt: skip
EXAMPLE_REQUESTS = {65260, 65259, 65226, 65227}


def name_with(**fields: int) -> Name:
    return replace(decode_name(SCAN_TOOL), **fields)


# -- DET-13, DET-18: classification at connection start ------------------------


def test_DET_13_wake_window_decides_not_in_baseline_or_external() -> None:
    early = classify(decode_name(SCAN_TOOL), 3.0, wake_window_s=10, trailer_vehicle_system=2)
    late = classify(decode_name(SCAN_TOOL), 29 * 60, wake_window_s=10, trailer_vehicle_system=2)
    assert early == ("vehicle ECU not in baseline", "high", "wake timing",
                     "first claim 3.0 s after the session's first frame")  # fmt: skip
    assert late[:3] == ("external device (unrecognized)", "high", "wake timing")
    assert late[3] == "first claim 29 min after the session's first frame"


def test_DET_18_trailer_name_is_a_trailer_device_at_notice() -> None:
    trailer = name_with(industry_group=1, vehicle_system=2)
    cat, sev, rule, detail = classify(trailer, 600, wake_window_s=10, trailer_vehicle_system=2)
    assert (cat, sev, rule) == ("trailer device", "notice", "NAME")  # DC-18
    assert detail == "industry group 1, vehicle system 2"
    other = name_with(industry_group=0, vehicle_system=2)
    assert classify(other, 600, wake_window_s=10, trailer_vehicle_system=2)[0] != "trailer device"


@pytest.mark.parametrize(
    ("kwargs", "rule", "reason"),
    [
        ({"requested": {65226}}, "request activity", "sent a diagnostic request (PGN 65226)"),
        ({"requested": {60928}}, None, None),  # a Request for Address Claim is not diagnostic
        ({"sent": {0}, "control_pgns": {0}}, "request activity", "sent control PGN 0"),
        ({"sent": {55552}}, "request activity", "sent memory access PGN 55552"),
        ({"claimed_known_address": True}, "NAME", "claimed an address held by a known ECU"),
    ],
)
def test_DET_18_trailer_is_reclassified_when_it_does_more_than_broadcast(
    kwargs: dict[str, Any], rule: Optional[str], reason: Optional[str]
) -> None:
    got = reclassify("trailer device", **kwargs)
    assert got == (None if rule is None else (rule, reason))


def test_DET_13_not_in_baseline_is_reclassified_by_requests_or_leaving_early() -> None:
    by_request = reclassify("vehicle ECU not in baseline", requested={65259})
    assert by_request is not None and by_request[0] == "request activity"
    got = reclassify("vehicle ECU not in baseline", ended_before_session=True)
    assert got == ("wake timing", "stopped sending before the session ended")
    assert reclassify("vehicle ECU not in baseline", claimed_known_address=True) is None
    assert reclassify("external device (unrecognized)", requested={65226}) is None


def test_DET_18_reclassified_identification_is_unrecognized_and_high() -> None:
    trailer = conn(category="trailer device")
    why = ("request activity", "sent a diagnostic request (PGN 65226)")
    ident = identify(
        trailer,
        [],
        {65226},
        library(),
        tie_margin=TIE,
        classification_rule="NAME",
        reclassified=why,
    )
    assert (ident.category, ident.sev, ident.classification_rule) == (
        "external device (unrecognized)", "high", "request activity",
    )  # fmt: skip
    assert ident.reclassified == "sent a diagnostic request (PGN 65226)"


# -- IDN-4: library score -------------------------------------------------------


def test_IDN_4_session_142_scan_tool_is_a_code_reader_at_medium() -> None:
    ident = identify(conn(), EXAMPLE_OUTCOMES, EXAMPLE_REQUESTS, library(), tie_margin=TIE)
    assert ident.type_guess == "diagnostic tool, code reader"  # 0.8, next best 0.6
    assert (ident.make, ident.model, ident.make_source) == (
        "unknown (mfr code 413; no manufacturer list loaded)", None, "none",
    )  # fmt: skip
    assert (ident.confidence, ident.id_source) == ("medium", ["NAME", "request pattern"])
    assert ident.candidates is None and ident.profile_match is None


def test_IDN_4_record_matches_the_example_identification() -> None:
    lines = (EXAMPLES / "s000142_20261106T140211Z.jsonl").read_text(encoding="utf-8")
    example = next(r for r in map(json.loads, lines.splitlines()) if r["rec"] == 6)
    ident = identify(conn(), EXAMPLE_OUTCOMES, EXAMPLE_REQUESTS, library(), tie_margin=TIE)
    rec = identification_record(conn(), ident, EXAMPLE_OUTCOMES,
                                lambda t: START + timedelta(seconds=t - 100.0))  # fmt: skip
    assert (rec.type, rec.sev, rec.conn) == ("identification", "notice", 2)
    for key in ("sa", "requests", "make", "model", "make_source", "type_guess", "confidence",
                "id_source"):  # fmt: skip
        assert rec.fields[key] == example[key], key


def test_IDN_4_specific_product_is_a_library_profile_match() -> None:
    requested = {65226, 65227, 65230, 65231, 65242, 65259, 64965}
    ident = identify(conn(), [], requested, library(), tie_margin=TIE)
    assert ident.type_guess == "diagnostic tool, heavy-duty scan tool"
    assert (ident.make, ident.model, ident.make_source) == (
        "Example Co. (illustrative)", "Demo-1 (illustrative)", "library",
    )  # fmt: skip
    assert ident.profile_match == "matches Example Co. (illustrative) Demo-1 (illustrative) profile"
    assert ident.confidence == "low"  # NAME and pattern (medium), library-only make: one step down


def test_IDN_4_near_tie_between_specific_and_generic_reports_the_type_only() -> None:
    lib = Library("lib-v9", (
        entry("ELD", typical=(65260, 65217, 65248, 65253)),
        entry("ELD", make="Acme", model="E-1", typical=(65260, 65217, 65248, 65253, 65254)),
    ), {})  # fmt: skip
    ident = identify(conn(), [], {65260, 65217, 65248, 65253}, lib, tie_margin=TIE)
    assert (ident.type_guess, ident.make_source, ident.profile_match) == ("ELD", "none", None)
    assert ident.make.startswith("unknown")


def test_IDN_4_near_tie_between_types_reports_the_broader_category() -> None:
    lib = Library("lib-v9", (
        entry("diagnostic tool, code reader", typical=(65226, 65227, 65259)),
        entry("diagnostic tool, service tool", typical=(65226, 65227, 65242)),
    ), {})  # fmt: skip
    ident = identify(conn(), [], {65226, 65227}, lib, tie_margin=TIE)
    assert ident.type_guess == "diagnostic tool"
    assert ident.candidates == ["diagnostic tool, code reader", "diagnostic tool, service tool"]
    assert ident.confidence == "low"  # one source (pattern), and the tie lowers it
    lib2 = Library(
        "lib-v9", (entry("ELD", typical=(1, 2)), entry("telematics", typical=(1, 3))), {}
    )
    assert identify(conn(), [], {1}, lib2, tie_margin=TIE).type_guess == "external device"


def test_IDN_4_function_gate_and_never_penalty() -> None:
    ecu = 0x0000000000000000 | (0 << 40)  # function 0
    ident = identify(conn(ecu), [], {65260, 65217, 65248, 65253, 65254, 65265}, library(),
                     tie_margin=TIE)  # fmt: skip
    assert ident.type_guess == "ELD"  # the diagnostic-tool entries need function 129
    plain = identify(conn(ecu), [], {65260, 65217}, library(), tie_margin=TIE)
    assert plain.type_guess == "ELD"  # 2/6 = 0.33
    penalised = identify(conn(ecu), [], {65260, 65235}, library(), tie_margin=TIE)
    assert penalised.type_guess is None  # 1/7 - 0.25 for DM11 (requests_never), floor 0
    assert penalised.id_source == []


def test_IDN_4_sa_hint_breaks_an_exact_tie_only() -> None:
    lib = Library("lib-v9", (
        entry("ELD", make="A", typical=(1, 2), hints=(250,)),
        entry("ELD", make="B", typical=(1, 2), hints=(249,)),
    ), {})  # fmt: skip
    assert identify(conn(sa=249), [], {1, 2}, lib, tie_margin=TIE).make == "B"
    lib_near = Library("lib-v9", (
        entry("ELD", make="A", typical=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)),
        entry("ELD", make="B", typical=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11), hints=(249,)),
    ), {})  # fmt: skip
    near = identify(conn(sa=249), [], set(range(1, 11)), lib_near, tie_margin=TIE)
    assert near.make_source == "none"  # 1.0 vs 0.91: within the margin, not exact; no hint


def test_IDN_4_no_library_match_gives_no_type() -> None:
    ident = identify(conn(), [], {61444}, library(), tie_margin=TIE)
    assert (ident.type_guess, ident.confidence) == (None, "low")
    assert identify(conn(), [], set(), None, tie_margin=TIE).type_guess is None


def test_IDN_4_changed_from_compares_type_make_and_model() -> None:
    a = identify(conn(), [], EXAMPLE_REQUESTS, library(), tie_margin=TIE)
    b = identify(conn(), [], {65226, 65227, 65230, 65231, 65242, 65259, 64965}, library(),
                 tie_margin=TIE)  # fmt: skip
    assert b.changed_from(a) and not a.changed_from(a)


# -- IDN-3: make and model --------------------------------------------------------


def test_IDN_3_self_reported_identity_comes_first_and_raises_confidence() -> None:
    outcomes = [reply(65259, b"Acme*CR-200*SN 1234*"), none(65242), none(64965, "NACK")]
    ident = identify(conn(), outcomes, EXAMPLE_REQUESTS, library(), tie_margin=TIE)
    assert (ident.make, ident.model, ident.make_source) == ("Acme", "CR-200", "self-reported")
    assert ident.id_source == ["NAME", "self-reported reply", "request pattern"]
    assert ident.confidence == "high"


def test_IDN_3_ecu_id_field_5_is_the_make() -> None:
    outcomes = [reply(64965, b"P123*S456*cab*tool*Beta Tools*")]
    ident = identify(conn(), outcomes, set(), None, tie_margin=TIE)
    assert (ident.make, ident.make_source) == ("Beta Tools", "self-reported")


def test_IDN_3_manufacturer_code_when_the_list_is_loaded() -> None:
    lib = with_codes(library(), {"413": "Gamma Diagnostics"})
    ident = identify(conn(), [], EXAMPLE_REQUESTS, lib, tie_margin=TIE)
    assert (ident.make, ident.make_source) == ("Gamma Diagnostics", "manufacturer code")
    missing = identify(conn(), [], EXAMPLE_REQUESTS, with_codes(library(), {"1": "X"}),
                       tie_margin=TIE)  # fmt: skip
    assert missing.make == "unknown (mfr code 413 not in the list)"


def test_IDN_3_disagreeing_sources_keep_each_value() -> None:
    lib = with_codes(library(), {"413": "Gamma Diagnostics"})
    outcomes = [reply(65259, b"Acme*CR-200*SN 1*")]
    ident = identify(conn(), outcomes, EXAMPLE_REQUESTS, lib, tie_margin=TIE)
    assert ident.make == "Acme"
    assert ident.disagreements == [
        {"source": "self-reported", "make": "Acme", "model": "CR-200"},
        {"source": "manufacturer code", "make": "Gamma Diagnostics", "model": None},
    ]


def test_IDN_3_device_without_a_name() -> None:
    ident = identify(conn(None, sa=200), [], {65260, 65217, 65248, 65253}, library(),
                     tie_margin=TIE)  # fmt: skip
    assert ident.make == "unknown (no NAME)" and ident.type_guess == "ELD"
    assert ident.id_source == ["request pattern"]


def test_IDN_3_reply_text_drops_the_trailing_star_and_the_software_id_count() -> None:
    assert reply_text(65242, b"\x01VDT 4.2.1*") == "VDT 4.2.1"
    assert reply_text(65259, b"Acme*CR-200*SN 1*\xff\xff") == "Acme*CR-200*SN 1"
    assert reply_text(65259, None) is None


# -- IDN-6: severity --------------------------------------------------------------


@pytest.mark.parametrize(
    ("category", "untrained", "sev"),
    [
        ("external device (unrecognized)", False, "high"),
        ("vehicle ECU not in baseline", False, "high"),
        ("trailer device", False, "notice"),
        ("external device (approved)", False, "info"),
        ("external device (unrecognized)", True, "notice"),
    ],
)
def test_IDN_6_connection_severity_by_category(category: str, untrained: bool, sev: str) -> None:
    assert severity(category, untrained) == sev


def test_IDN_6_identification_record_is_notice() -> None:
    ident = identify(conn(), [], EXAMPLE_REQUESTS, library(), tie_margin=TIE)
    assert isinstance(ident, Identification)
    rec = identification_record(conn(), ident, [], lambda t: None)
    assert rec.sev == "notice" and rec.fields["reclassified"] is None
