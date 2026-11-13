"""config: validation of config, inventory and library files."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from j1939logger.config import (
    Config,
    ConfigError,
    Inventory,
    InventoryError,
    Library,
    LibraryError,
    change_record,
    parse_json,
    rejected_record,
    validate,
    validate_inventory,
    validate_library,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"


def load(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def cfg3() -> dict[str, Any]:
    data: dict[str, Any] = load("cfg-v3.json")
    return data


def ok(data: dict[str, Any], old: Config | None = None) -> Config:
    result = validate(data, old)
    assert isinstance(result, Config), result
    return result


def bad(data: Any, old: Config | None = None) -> list[str]:
    result = validate(data, old)
    assert isinstance(result, ConfigError), result
    return result.reasons


def test_LOG_13_example_config_validates_with_its_version() -> None:
    cfg = ok(cfg3())
    assert (cfg.version, cfg.number) == ("cfg-v3", 3)
    assert cfg["limits.tp_sessions"] == 32
    assert cfg["address.name"] == "0x9FFEFFFFFFE00001"


def test_STS_9_unknown_and_missing_keys_are_rejected_and_listed() -> None:
    data = cfg3()
    data["detection"]["flood_limit"] = 20
    del data["clock"]["max_skew_min"]
    reasons = bad(data)
    assert "unknown key detection.flood_limit" in reasons
    assert "missing key clock.max_skew_min" in reasons


def test_STS_9_wrong_types_are_rejected() -> None:
    data = cfg3()
    data["limits"]["tp_sessions"] = "32"
    data["detection"]["known_device_new_pgn"] = 1
    assert set(bad(data)) == {
        "bad value for limits.tp_sessions",
        "bad value for detection.known_device_new_pgn",
    }


def test_STS_9_allow_list_additions_are_rejected() -> None:
    data = cfg3()
    data["transmit"]["allow_list"].append(61184)
    data["requests"]["allow_list"].append(65226)
    reasons = bad(data)
    assert any(r.startswith("transmit.allow_list adds [61184]") for r in reasons)
    assert any(r.startswith("requests.allow_list adds [65226]") for r in reasons)


def test_STS_9_allow_list_can_narrow_but_not_widen_again() -> None:
    narrow = cfg3()
    narrow["requests"]["allow_list"] = [60928, 65260]
    narrow["config"] = "cfg-v4"
    old = ok(narrow)
    back = cfg3()
    back["config"] = "cfg-v5"
    reasons = bad(back, old)
    assert any(r.startswith("requests.allow_list adds") for r in reasons)


def test_STS_9_move_grace_over_5_s_is_rejected() -> None:
    data = cfg3()
    data["detection"]["move_grace_s"] = 6
    assert bad(data) == ["detection.move_grace_s over 5 s"]


def test_STS_9_detection_weakening_changes_are_flagged_and_high() -> None:
    old = ok(cfg3())
    new = cfg3()
    new["config"] = "cfg-v4"
    new["detection"]["control_pgns"].remove(1024)
    new["detection"]["known_device_new_pgn"] = False
    new["logging"]["raw_before_s"] = 5
    new["detection"]["silence_end_s"] = 90
    new["detection"]["move_grace_s"] = 2
    cfg = ok(new, old)
    assert len(cfg.weakens) == 5
    rec = change_record(cfg, old, "jdoe", None)
    assert (rec.type, rec.sev, rec.fields["weakens_detection"]) == ("config_change", "high", True)
    assert rec.fields["old_version"] == "cfg-v3" and rec.fields["new_version"] == "cfg-v4"


def test_STS_9_ordinary_change_is_notice_and_lists_changed_fields() -> None:
    old = ok(cfg3())
    new = cfg3()
    new["config"] = "cfg-v4"
    new["requests"]["sweep_interval_min"] = 15
    cfg = ok(new, old)
    assert cfg.changed == ("requests.sweep_interval_min",) and cfg.weakens == ()
    assert change_record(cfg, old, "jdoe", None).sev == "notice"


def test_STS_9_rejected_push_gives_config_rejected_record() -> None:
    err = validate({"format": "cfg-1"})
    assert isinstance(err, ConfigError)
    rec = rejected_record(err, "cfg-v4", "jdoe", None)
    assert (rec.type, rec.sev) == ("config_rejected", "notice")
    assert rec.fields["reasons"] == err.reasons


def test_LOG_19_unknown_formats_are_refused() -> None:
    data = cfg3()
    data["format"] = "cfg-2"
    assert bad(data) == ["unknown config format 'cfg-2'"]
    inv = load("inv-v2.json")
    inv["format"] = "inv-9"
    assert isinstance(validate_inventory(inv), InventoryError)
    lib = load("lib-v1.json")
    lib["format"] = "lib-2"
    assert isinstance(validate_library(lib), LibraryError)


def test_STS_19_corrupt_config_file_is_detected() -> None:
    try:
        parse_json(b'{"format": "cfg-1",')
    except ValueError as exc:
        assert "not valid JSON" in str(exc)
    else:
        raise AssertionError("corrupt JSON accepted")
    assert bad([1, 2]) == ["config is not a JSON object"]


def test_TRN_7_example_inventory_validates() -> None:
    inv = validate_inventory(load("inv-v2.json"))
    assert isinstance(inv, Inventory)
    assert inv.version == "inv-v2"
    assert [e.entry for e in inv.entries] == ["E01", "E02", "E03", "E04"]
    assert inv.by_name()[0x8000FE003C04D2E8].category == "external device (approved)"


def test_STS_19_corrupt_inventory_is_rejected_with_reasons() -> None:
    inv = load("inv-v2.json")
    broken = copy.deepcopy(inv)
    broken["entries"][0]["name"] = "0xNOTHEX"
    broken["entries"][1]["category"] = "friendly ECU"
    broken["entries"][2]["entry"] = "E01"
    result = validate_inventory(broken)
    assert isinstance(result, InventoryError)
    assert len(result.reasons) == 3


def test_IDN_5_example_library_validates_with_empty_manufacturer_list() -> None:
    lib = validate_library(load("lib-v1.json"))
    assert isinstance(lib, Library)
    assert lib.version == "lib-v1" and len(lib.devices) >= 1
    assert dict(lib.manufacturers) == {}  # shipped empty (IDN-2)


def test_IDN_2_manufacturer_codes_are_read_from_the_library() -> None:
    lib = load("lib-v1.json")
    lib["manufacturers"]["codes"] = {"413": "Example Tools Inc"}
    result = validate_library(lib)
    assert isinstance(result, Library)
    assert result.manufacturers["413"] == "Example Tools Inc"
    lib["manufacturers"]["codes"] = {"abc": 1}
    assert isinstance(validate_library(lib), LibraryError)
