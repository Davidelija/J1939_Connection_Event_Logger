"""store: supporting files, versions, atomic writes, state.json on flash, faults."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from j1939logger.platform.desktop import DesktopPlatform, FakeClock, FaultSpec
from j1939logger.store import KINDS, Store


def make(
    tmp_path: Path, plan: Sequence[FaultSpec] = ()
) -> tuple[Store, DesktopPlatform, FakeClock]:
    fc = FakeClock()
    p = DesktopPlatform(fault_plan=plan, clock=fc, root=tmp_path)
    return Store(p), p, fc


def test_LOG_23_round_trip_of_every_kind(tmp_path: Path) -> None:
    store, p, _ = make(tmp_path)
    names = {"status": "status", "inventory": "inv-v2", "config": "cfg-v3", "library": "lib-v1"}
    names["state"] = "state"
    for kind in KINDS:
        assert store.write_atomic(kind, names[kind], f'{{"kind":"{kind}"}}'.encode())
        assert json.loads(store.load(kind) or b"{}") == {"kind": kind}
    assert (p.paths().card / "inventory" / "inv-v2.json").exists()
    assert (p.paths().card / "config" / "cfg-v3.json").exists()
    assert (p.paths().card / "library" / "lib-v1.json").exists()
    assert (p.paths().card / "status.json").exists()


def test_LOG_5_state_json_is_on_internal_flash_not_the_card(tmp_path: Path) -> None:
    store, p, _ = make(tmp_path)
    store.write_atomic("state", "state", b'{"format":"state-1"}')
    assert (p.paths().flash / "state.json").exists()
    assert not (p.paths().card / "state.json").exists()


def test_LOG_23_missing_file_loads_as_none(tmp_path: Path) -> None:
    store, _, _ = make(tmp_path)
    assert store.load("status") is None
    assert store.load("inventory") is None
    assert store.load("config", 7) is None


def test_TRN_6_versions_are_listed_and_newest_loads_by_default(tmp_path: Path) -> None:
    store, _, _ = make(tmp_path)
    for n in (1, 3, 2):
        store.write_atomic("inventory", f"inv-v{n}", f"{n}".encode())
    assert store.versions("inventory") == [1, 2, 3]
    assert store.load("inventory") == b"3"
    assert store.load("inventory", 1) == b"1"


def test_LOG_23_version_files_are_never_overwritten(tmp_path: Path) -> None:
    store, _, _ = make(tmp_path)
    store.write_atomic("config", "cfg-v3", b"a")
    with pytest.raises(ValueError):
        store.write_atomic("config", "cfg-v3", b"b")
    assert store.load("config", 3) == b"a"
    with pytest.raises(ValueError):
        store.write_atomic("config", "inv-v4", b"x")


def test_LOG_23_status_is_overwritten_in_place_atomically(tmp_path: Path) -> None:
    store, p, _ = make(tmp_path)
    store.write_atomic("status", "status", b"one")
    store.write_atomic("status", "status", b"two")
    assert store.load("status") == b"two"
    assert not list(p.paths().card.glob(".*.tmp"))


def test_LOG_23_leftover_temporary_files_are_ignored(tmp_path: Path) -> None:
    store, p, _ = make(tmp_path)
    store.write_atomic("inventory", "inv-v1", b"good")
    (p.paths().card / "inventory" / ".inv-v2.json.tmp").write_bytes(b"half")
    assert store.versions("inventory") == [1]
    assert store.load("inventory") == b"good"


def test_LOG_22_card_write_error_gives_high_fault_and_keeps_old_file(tmp_path: Path) -> None:
    store, _, fc = make(tmp_path, [(1001.0, "enospc", {"for_s": 1.0})])
    store.write_atomic("status", "status", b"old")
    fc.advance(1.0)
    assert store.write_atomic("status", "status", b"new") is False
    [fault] = store.take_faults()
    assert (fault.type, fault.sev) == ("fault", "high")
    assert "enospc" in fault.fields["cause"]
    assert store.load("status") == b"old"


def test_LOG_5_state_unwritable_hits_state_json_only(tmp_path: Path) -> None:
    store, _, _ = make(tmp_path, [(0.0, "state_unwritable", None)])
    assert store.write_atomic("status", "status", b"ok") is True
    assert store.write_atomic("state", "state", b"{}") is False
    assert "state_unwritable" in store.take_faults()[0].fields["cause"]


def test_LOG_11_free_removes_only_raw_captures(tmp_path: Path) -> None:
    store, p, _ = make(tmp_path)
    raw = p.paths().card / "raw"
    raw.mkdir()
    cap = raw / "s000142_c2_e1.log"
    cap.write_text("x")
    sessions = p.paths().card / "sessions"
    sessions.mkdir()
    sess = sessions / "s000142_20261106T140211Z.jsonl"
    sess.write_text("{}\n")
    assert store.free([cap]) == 1 and not cap.exists()
    with pytest.raises(ValueError):
        store.free([sess])
    assert sess.exists()


def test_STS_3_card_usage_is_reported(tmp_path: Path) -> None:
    store, _, _ = make(tmp_path)
    u = store.usage()
    assert u.total_bytes > 0 and 0.0 <= u.used_pct <= 100.0
