"""Step 7 in the session: the command handlers behind cmdserver (step 7 PR 1, DC-21)."""

from __future__ import annotations

import json
import shutil
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

from j1939logger.admin import RESTART_EXIT
from j1939logger.config import Inventory
from j1939logger.main import inventory_from_file
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import Session, session_files, settings_from_config
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
ENGINE = 0x000000002E412A10
SCAN = 0x8000810033A1B2C4


class _Socket:
    def setsockopt(self, *a: Any) -> None: ...
    def getsockopt(self, *a: Any) -> int:
        return 1 << 20

    def settimeout(self, t: float) -> None: ...
    def recvmsg(self, *a: Any) -> Any:
        time.sleep(0.005)
        raise socket.timeout()

    def send(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None: ...


class Bus(DesktopPlatform):
    def open_can(self, listen_only: bool) -> socket.socket:
        return cast(socket.socket, _Socket())

    def bitrate_check(self) -> Optional[int]:
        return 250000


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def inventory() -> Inventory:
    return inventory_from_file(json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8")))


def make(root: Path, fc: Optional[FakeClock] = None) -> tuple[Session, FakeClock]:
    folder = root / "card" / "config"
    if not folder.is_dir():
        folder.mkdir(parents=True)
        shutil.copy(EXAMPLES / "cfg-v3.json", folder / "cfg-v3.json")
    fc = fc or FakeClock(start_utc=START, start_mono=100.0)
    versions = {"config": "cfg-v3", "inventory": "inv-v2", "library": None}
    return Session(Bus(clock=fc, root=root), settings(), inventory(), versions, None), fc


def frame(cid: int, data: bytes, t: float) -> Frame:
    return Frame(1.7e9 + t, t, cid, True, False, False, data, False)


def claim(name: int, sa: int, t: float) -> Frame:
    return frame(0x18EEFF00 | sa, name.to_bytes(8, "little"), t)


def run(s: Session, fc: FakeClock, seconds: float, *senders: int, step: float = 0.1) -> None:
    end = fc.mono() + seconds
    while fc.mono() < end:
        for sa in senders:
            s.capture._ingest(frame((6 << 26) | (65262 << 8) | sa, bytes(8), fc.mono()))
        s.step()
        fc.advance(step)


def records(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in session_files(root / "card" / "sessions"):
        out += [json.loads(x) for x in f.path.read_text("utf-8").splitlines()]
    return out


def with_scan_tool(tmp_path: Path) -> tuple[Session, FakeClock]:
    s, fc = make(tmp_path)
    s.start()
    s.capture._ingest(claim(ENGINE, 0, fc.mono()))
    run(s, fc, 3.0, 0)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 1.0, 0, 249)
    return s, fc


def state_json(root: Path) -> dict[str, Any]:
    found = list(root.rglob("state.json"))
    assert found
    data: dict[str, Any] = json.loads(found[0].read_text("utf-8"))
    return data


# -- STS-23: the protocol ------------------------------------------------------------


def test_STS_23_replies_follow_the_protocol_and_refuse_with_a_next_step(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    ok = s.handle("status")
    assert ok["proto"] == 1 and ok["ok"] is True and ok["result"]["state"] == "recording"
    bad = s.handle("nope", operator="jdoe")
    assert bad == {"proto": 1, "ok": False, "error": "unknown command 'nope'",
                   "next": "run j1939ctl --help"}  # fmt: skip
    nobody = s.handle("clear", {"events": ["1-5"]}, operator=None, reason="r")
    assert nobody["ok"] is False and nobody["error"] == "unknown operator key"


def test_LOG_8_login_and_logout_are_logged_with_the_operator(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    s.handle("login", {"tool_version": "1.0.0"}, operator="jdoe")
    s.handle("logout", {"tool_version": "1.0.0"}, operator="jdoe")
    recs = [r for r in records(tmp_path) if r["type"].startswith("operator_")]
    assert [(r["type"], r["sev"], r["operator"]) for r in recs] == [
        ("operator_login", "notice", "jdoe"), ("operator_logout", "info", "jdoe"),
    ]  # fmt: skip


# -- STS-2, LAP-4, LAP-11: review and clear ---------------------------------------------


def test_STS_2_high_events_stay_unreviewed_until_cleared(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    start = next(r for r in records(tmp_path) if r["type"] == "connection_start")
    event = f"1-{start['rec']}"
    status = s.handle("status")["result"]
    assert event in status["unreviewed"] and status["light"] == "slow"
    assert event in state_json(tmp_path)["unreviewed"]  # kept across sessions
    events = s.handle("events")["result"]["events"]
    assert [e["event"] for e in events] == [event]


def test_LAP_4_clear_needs_unreviewed_ids_and_a_reason(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    event = s.handle("status")["result"]["unreviewed"][0]
    assert (
        s.handle("clear", {"events": [event]}, operator="jdoe")["error"] == "a reason is required"
    )
    wrong = s.handle("clear", {"events": ["1-999"]}, operator="jdoe", reason="RO 1")
    assert wrong["ok"] is False and "1-999" in wrong["error"]
    done = s.handle("clear", {"events": [event], "disposition": "shop scan tool"},
                    operator="jdoe", reason="RO 55812")  # fmt: skip
    assert done["ok"] and done["result"]["light"] == "steady"
    [rec] = [r for r in records(tmp_path) if r["type"] == "review_clear"]
    assert (rec["cleared"], rec["reason"], rec["disposition"]) == ([event], "RO 55812",
                                                                   "shop scan tool")  # fmt: skip
    assert state_json(tmp_path)["unreviewed"] == []


def test_LAP_11_approve_clears_its_event_in_the_same_step(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    event = s.handle("status")["result"]["unreviewed"][0]
    reply = s.handle("approve", {"event": event}, operator="jdoe", reason="fleet ELD")
    assert reply["ok"] and reply["result"] == {"inventory": "inv-v3", "cleared": [event]}
    assert s.handle("status")["result"]["unreviewed"] == []
    [rec] = [r for r in records(tmp_path) if r["type"] == "approval"]
    assert rec["kind"] == "device" and rec["events_cleared"] == [event]


# -- STS-9: config push --------------------------------------------------------------------


def pushed(**changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8"))
    doc["config"] = "cfg-v4"
    for path, value in changes.items():
        group, key = path.split("__")
        doc[group][key] = value
    return doc


def test_STS_9_config_push_saves_a_new_version_and_logs_the_change(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    reply = s.handle("config_push", {"config": pushed(detection__requests_kept=50)},
                     operator="jdoe")  # fmt: skip
    assert reply["ok"] and reply["result"]["config"] == "cfg-v4"
    assert (tmp_path / "card" / "config" / "cfg-v4.json").exists()
    [rec] = [r for r in records(tmp_path) if r["type"] == "config_change"]
    assert rec["sev"] == "notice" and "detection.requests_kept" in rec["changed"]


def test_STS_9_weakening_needs_confirm_and_is_high(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    weaker = pushed(detection__silence_end_s=120)
    refused = s.handle("config_push", {"config": weaker}, operator="jdoe")
    assert refused["ok"] is False and "--confirm" in refused["error"]
    ok = s.handle("config_push", {"config": weaker, "confirm": True}, operator="jdoe")
    assert ok["ok"]
    [rec] = [r for r in records(tmp_path) if r["type"] == "config_change"]
    assert rec["sev"] == "high" and rec["weakens_detection"] is True


def test_STS_9_a_bad_config_is_rejected_and_logged(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    bad = pushed()
    bad["transmit"]["allow_list"] = [*bad["transmit"]["allow_list"], 0]
    reply = s.handle("config_push", {"config": bad}, operator="jdoe")
    assert reply["ok"] is False and "config rejected" in reply["error"]
    [rec] = [r for r in records(tmp_path) if r["type"] == "config_rejected"]
    assert rec["proposed_version"] == "cfg-v4"
    assert not (tmp_path / "card" / "config" / "cfg-v4.json").exists()


# -- STS-11, STS-12: restart and retrain ---------------------------------------------------


def test_STS_11_restart_logs_reset_and_ends_with_exit_code_75(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    assert s.handle("restart", operator="jdoe")["error"] == "a reason is required"
    reply = s.handle("restart", operator="jdoe", reason="after config push")
    assert reply["result"] == {"exit_code": RESTART_EXIT} and s.exit_code == 75
    s.run()  # stop() was requested: run returns and closes the session
    recs = records(tmp_path)
    reset = next(r for r in recs if r["type"] == "reset")
    assert (reset["mode"], reset["reason"]) == ("restart", "after config push")
    assert recs[-1]["type"] == "connection_end" and recs[-1]["end_reason"] == "software restart"
    assert s.diag.last_restart_cause() == "software restart"
    s2, fc2 = make(tmp_path, FakeClock(start_utc=START, start_mono=500.0))
    s2.start()  # after systemd restarts it
    run(s2, fc2, 1.0, 0)
    header = [r for r in records(tmp_path) if r["type"] == "session_start"][-1]
    assert header["prev_session_end"] == "software restart"  # LOG-18


def test_STS_12_retrain_runs_the_next_session_untrained(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    reply = s.handle("retrain", operator="jdoe", reason="new engine")
    assert reply["result"] == {"archived": "inv-v2"}
    assert state_json(tmp_path)["inventory_active"] is False
    run(s, fc, 31.0)  # key-off ends the session
    run(s, fc, 1.0, 0)  # the next session
    headers = [r for r in records(tmp_path) if r["type"] == "session_start"]
    assert [h["untrained"] for h in headers] == [False, True]
    [reset] = [r for r in records(tmp_path) if r["type"] == "reset"]
    assert (reset["mode"], reset["archived"]) == ("retrain", "inv-v2")


# -- TRN-6: a saved version applies from the next session ------------------------------------


def test_TRN_6_a_saved_inventory_applies_from_the_next_session(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    event = s.handle("status")["result"]["unreviewed"][0]
    s.handle("approve", {"event": event}, operator="jdoe", reason="fleet ELD")
    run(s, fc, 31.0)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run(s, fc, 4.0, 0, 249)
    headers = [r for r in records(tmp_path) if r["type"] == "session_start"]
    assert [h["inventory"] for h in headers] == ["inv-v2", "inv-v3"]
    starts = [r for r in records(tmp_path) if r["type"] == "connection_start" and r["sa"] == 249]
    assert starts[-1]["category"] == "external device (approved)" and starts[-1]["sev"] == "info"


# -- LAP-5, LOG-11: retrieval bookkeeping ---------------------------------------------------


def test_LAP_5_retrieved_files_are_logged_and_listed(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    listing = s.handle("retrieve_list")["result"]["files"]
    paths = [f["path"] for f in listing]
    assert any(p.startswith("sessions/s000001_") for p in paths)
    assert all(len(f["sha256"]) == 64 for f in listing)
    reply = s.handle("retrieved", {"files": paths, "chain": True, "last_hash": "ab" * 32},
                     operator="jdoe")  # fmt: skip
    assert reply["ok"]
    [rec] = [r for r in records(tmp_path) if r["type"] == "retrieval"]
    assert (rec["sessions"], rec["partial"], rec["chain_verified"]) == ([1], [1], True)
    assert s.handle("status")["result"]["retrieved"] == ["s000001"]
    assert set(paths) <= set(state_json(tmp_path)["retrieved"])


def test_STS_3_the_status_file_is_kept_on_the_card(tmp_path: Path) -> None:
    s, fc = with_scan_tool(tmp_path)
    found = list((tmp_path / "card").rglob("status.json"))
    assert found
    body = json.loads(found[0].read_text("utf-8"))
    assert (body["format"], body["state"], body["session"]) == ("status-1", "recording", 1)
    assert body["unreviewed_high"] == 1 and body["light"] == "slow"
    assert s.status.pattern == "slow"
