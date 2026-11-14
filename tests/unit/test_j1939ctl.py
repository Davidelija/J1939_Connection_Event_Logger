"""j1939ctl end to end against an in-process logger (step 7 PR 3, DC-21).

``ssh`` is replaced by a runner that calls ``j1939cmd`` directly and ``scp`` by a
copy from the card, as the j1939ctl contract's test seam says.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import stat
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

import pytest

from j1939ctl.cli import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, main
from j1939logger.j1939cmd import run
from j1939logger.main import inventory_from_file
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import Session, session_files, settings_from_config
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
ENGINE = 0x000000002E412A10
SCAN = 0x8000810033A1B2C4
VIN = "1XKYD49X0GJ123456"


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


class Local:
    """The j1939ctl transport, with ssh replaced by j1939cmd's run() and scp by a copy."""

    def __init__(self, s: Session, card: Path, operator: Optional[str] = "jdoe") -> None:
        self.s, self.card, self.operator = s, card, operator
        self.sent: list[dict[str, Any]] = []
        self.down = False

    def call(self, cmd: str, args: Optional[dict[str, Any]] = None,
             reason: Optional[str] = None) -> tuple[dict[str, Any], int]:  # fmt: skip
        line = json.dumps({"cmd": cmd, "args": args or {}, "reason": reason})

        def send(path: Path, msg: dict[str, Any]) -> dict[str, Any]:
            if self.down:
                raise ConnectionRefusedError
            self.sent.append(msg)
            return self.s.handle(msg["cmd"], msg["args"], msg["operator"], msg["reason"])

        return run(line, operator=self.operator, socket_path=self.card / "x.sock", card=self.card,
                   send=send)  # fmt: skip

    def fetch(self, remote: str, local: Path) -> None:
        shutil.copyfile(self.card / remote, local)


def settings() -> dict[str, Any]:
    return settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))


def frame(cid: int, data: bytes, t: float) -> Frame:
    return Frame(1.7e9 + t, t, cid, True, False, False, data, False)


def claim(name: int, sa: int, t: float) -> Frame:
    return frame(0x18EEFF00 | sa, name.to_bytes(8, "little"), t)


def run_bus(s: Session, fc: FakeClock, seconds: float, *senders: int) -> None:
    end = fc.mono() + seconds
    while fc.mono() < end:
        for sa in senders:
            s.capture._ingest(frame((6 << 26) | (65262 << 8) | sa, bytes(8), fc.mono()))
        s.step()
        fc.advance(0.1)


@pytest.fixture
def logger(tmp_path: Path) -> Iterator[tuple[Session, FakeClock, Local]]:
    root = tmp_path / "logger"
    (root / "card" / "config").mkdir(parents=True)
    shutil.copy(EXAMPLES / "cfg-v3.json", root / "card" / "config" / "cfg-v3.json")
    fc = FakeClock(start_utc=START, start_mono=100.0)
    inv = inventory_from_file(json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8")))
    s = Session(Bus(clock=fc, root=root), settings(), inv, {"config": "cfg-v3"}, None)
    s.start()
    s.capture._ingest(claim(ENGINE, 0, fc.mono()))
    run_bus(s, fc, 3.0, 0)
    s.capture._ingest(claim(SCAN, 249, fc.mono()))
    run_bus(s, fc, 1.0, 0, 249)
    yield s, fc, Local(s, root / "card")
    for p in tmp_path.rglob("*"):  # let pytest clean up read-only files
        if p.is_file():
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)


def ctl(t: Local, *argv: str, answers: tuple[str, ...] = ()) -> tuple[int, str]:
    out = io.StringIO()
    it = iter(answers)
    code = main(list(argv), transport=t, out=out, ask=lambda q: next(it))
    return code, out.getvalue()


def records(s: Session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in session_files(s._sessions_dir):
        out += [json.loads(x) for x in f.path.read_text("utf-8").splitlines() if x.endswith("}")]
    return out


# -- LAP-10, LAP-17: the home screen ------------------------------------------------------


def test_LAP_10_status_is_the_home_screen_with_a_next_step(logger: Any) -> None:
    s, fc, t = logger
    code, text = ctl(t, "status")
    assert code == EXIT_OK
    assert "Events to review: 1" in text and "Training needed: no" in text
    assert "from this laptop" in text  # the clock difference, never set (LAP-10 (a))
    assert text.strip().splitlines()[-1] == "Next step: 1 event to review: run events"


def test_LOG_8_each_run_is_bracketed_by_login_and_logout(logger: Any) -> None:
    s, fc, t = logger
    ctl(t, "status")
    assert [m["cmd"] for m in t.sent] == ["login", "status", "logout"]
    types = [r["type"] for r in records(s)]
    assert types[-2:] == ["operator_login", "operator_logout"]


def test_LAP_17_events_use_plain_words(logger: Any) -> None:
    s, fc, t = logger
    code, text = ctl(t, "events")
    assert code == EXIT_OK and "ECU not in training" in text and "0x8000810033A1B2C4" in text
    assert "vehicle ECU not in baseline" not in text


# -- LAP-3, LAP-4, LAP-11, LAP-15: prompts and refusals ---------------------------------------


def test_LAP_3_changing_commands_show_the_change_ask_a_reason_then_y_n(logger: Any) -> None:
    s, fc, t = logger
    event = s.handle("status")["result"]["unreviewed"][0]
    code, text = ctl(t, "clear", event, answers=("RO 55812", "n"))
    assert code == EXIT_REFUSED and "This will:" in text and "Nothing changed." in text
    assert not any(m["cmd"] == "clear" for m in t.sent)
    code, text = ctl(t, "clear", event, "--disposition", "shop tool", answers=("RO 55812", "y"))
    assert code == EXIT_OK and "Cleared 1. Light is now steady." in text


def test_LAP_11_approve_with_reason_and_yes_clears_the_event(logger: Any) -> None:
    s, fc, t = logger
    event = s.handle("status")["result"]["unreviewed"][0]
    code, text = ctl(t, "--yes", "approve", event, "--reason", "fleet ELD")
    assert code == EXIT_OK and f"event {event} cleared" in text
    assert s.handle("status")["result"]["unreviewed"] == []


def test_LAP_15_refusals_say_why_and_what_to_do_with_a_nonzero_exit(logger: Any) -> None:
    s, fc, t = logger
    code, text = ctl(t, "--yes", "approve", "1-999", "--reason", "x")
    assert code == EXIT_REFUSED and "Refused: no event 1-999" in text and "Next step:" in text
    code, text = ctl(t, "--yes", "remove", "E99", "--reason", "x")
    assert code == EXIT_REFUSED and "Next step: run inventory show" in text
    assert ctl(t, "nosuchcommand")[0] == EXIT_USAGE
    assert ctl(t, "approve", "--help")[0] == EXIT_OK


def test_LAP_3_removing_a_training_ecu_shows_a_warning_line(logger: Any) -> None:
    s, fc, t = logger
    code, text = ctl(t, "remove", "E02", answers=("ECU replaced", "y"))
    assert code == EXIT_OK and "WARNING: this ECU was found in training" in text
    [rec] = [r for r in records(s) if r["type"] == "inventory_remove"]
    assert rec["warning_shown"] is True


def test_STS_5_an_unknown_key_is_refused_with_the_next_step(logger: Any) -> None:
    s, fc, t = logger
    t.operator = None
    code, text = ctl(t, "--yes", "restart", "--reason", "x")
    assert code == EXIT_REFUSED and "not an operator key" in text


def test_STS_23_status_still_works_when_the_service_is_down(logger: Any) -> None:
    s, fc, t = logger
    t.down = True
    code, text = ctl(t, "status")
    assert code == EXIT_OK and "last saved status" in text
    code, text = ctl(t, "--yes", "clear", "1-5", "--reason", "x")
    assert code == 3 and "logger not running" in text


# -- STS-9, STS-17: config push ---------------------------------------------------------------


def test_STS_17_config_push_is_validated_on_the_laptop_first(logger: Any, tmp_path: Path) -> None:
    s, fc, t = logger
    bad = json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8"))
    bad["config"] = "cfg-v4"
    bad["transmit"]["allow_list"].append(0)
    path = tmp_path / "cfg-v4.json"
    path.write_text(json.dumps(bad), "utf-8")
    code, text = ctl(t, "--yes", "config", "push", str(path), "--reason", "x")
    assert code == EXIT_REFUSED and "nothing was sent" in text
    assert not any(m["cmd"] == "config_push" for m in t.sent)
    good = json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8"))
    good["config"] = "cfg-v4"
    good["detection"]["silence_end_s"] = 90  # weakens detection
    path.write_text(json.dumps(good), "utf-8")
    assert ctl(t, "--yes", "config", "push", str(path), "--reason", "x")[0] == EXIT_REFUSED
    code, text = ctl(t, "--yes", "config", "push", str(path), "--confirm", "--reason", "x")
    assert code == EXIT_OK and "Saved cfg-v4" in text


# -- TRN-4, LAP-14: training --------------------------------------------------------------------


def test_TRN_4_train_finish_asks_before_applying(logger: Any) -> None:
    s, fc, t = logger
    assert ctl(t, "--yes", "train", "start")[0] == EXIT_OK
    run_bus(s, fc, 1.0, 0)
    code, text = ctl(t, "train", "status")
    assert code == EXIT_OK and "Conditions covered:" in text and "Devices found:" in text
    code, text = ctl(t, "train", "finish", answers=("n",))
    assert code == EXIT_OK and "Proposed inventory inv-v3" in text and "Not applied" in text
    assert [r["type"] for r in records(s) if r["type"] in ("approval", "rejection")] == [
        "rejection"
    ]


# -- LAP-5, LAP-6, LAP-9: retrieval ---------------------------------------------------------------


def test_LAP_5_retrieve_copies_new_files_checks_the_chain_and_tells_the_logger(
    logger: Any, tmp_path: Path
) -> None:
    s, fc, t = logger
    logs = tmp_path / "logs"
    code, text = ctl(t, "--folder", str(logs), "retrieve")
    assert code == EXIT_OK, text
    folder = logs / VIN
    assert "Chain check: verified (open session in progress)" in text
    held = sorted(p.name for p in (folder / "sessions").iterdir())
    assert held and held[0].startswith("s000001_")
    assert not os.access(folder / "sessions" / held[0], os.W_OK)  # read-only
    assert (folder / "inventory" / "inv-v2.json").exists()  # for inventory show offline
    assert any(r["type"] == "retrieval" and r["chain_verified"] for r in records(s))
    run_bus(s, fc, 1.0, 0)
    code, text = ctl(t, "--folder", str(logs), "retrieve")  # again: the session grew
    assert code == EXIT_OK and "Chain check: verified" in text
    assert sorted(p.name for p in (folder / "sessions").iterdir()) == held  # replaced, no suffix
    state = json.loads((logs / ".j1939ctl.json").read_text("utf-8"))
    assert len(state[VIN]["last_hash"]) == 64


def test_LAP_5_a_same_name_file_with_other_content_is_kept_with_a_suffix(
    logger: Any, tmp_path: Path
) -> None:
    s, fc, t = logger
    logs = tmp_path / "logs"
    ctl(t, "--folder", str(logs), "retrieve")
    raw = t.card / "raw"
    raw.mkdir(exist_ok=True)
    (raw / "s000001_c9_e1.log").write_text("(1.0) can0 123#00\n", "ascii")
    ctl(t, "--folder", str(logs), "retrieve")
    (raw / "s000001_c9_e1.log").write_text("(2.0) can0 123#01\n", "ascii")
    code, text = ctl(t, "--folder", str(logs), "retrieve")
    assert "kept the new copy as raw/s000001_c9_e1.log.1" in text.replace("\\", "/")
    assert (logs / VIN / "raw" / "s000001_c9_e1.log.1").exists()


def test_LAP_6_a_partial_copy_is_copied_again(logger: Any, tmp_path: Path) -> None:
    s, fc, t = logger
    logs = tmp_path / "logs"
    ctl(t, "--folder", str(logs), "retrieve")
    session = sorted((t.card / "sessions").iterdir())[0].name
    part = logs / VIN / "sessions" / (session + ".part")
    os.chmod(part.parent, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    part.write_text("half a line", "utf-8")  # left by a dropped link
    run_bus(s, fc, 0.5, 0)
    code, text = ctl(t, "--folder", str(logs), "retrieve")
    assert code == EXIT_OK and not part.exists()


# -- STS-7, LAP-12, LAP-13: report and inventory offline -------------------------------------------


def test_STS_7_report_has_five_sections_in_order_and_events_csv(
    logger: Any, tmp_path: Path
) -> None:
    s, fc, t = logger
    logs = tmp_path / "logs"
    ctl(t, "--folder", str(logs), "retrieve")
    code, text = ctl(t, "report", str(logs / VIN))  # offline: no transport used
    assert code == EXIT_OK
    heads = [line for line in text.splitlines() if line[:2] in ("1.", "2.", "3.", "4.", "5.")]
    assert heads == ["1. Events to review", "2. New devices", "3. Changes since the last retrieval",
                     "4. Sessions and gaps", "5. Chain check"]  # fmt: skip
    assert "0x8000810033A1B2C4: 1 event(s)" in text and "latest chain hash:" in text
    csv_text = (logs / f"events-{VIN}.csv").read_text("utf-8")
    assert csv_text.splitlines()[0] == "event,session,utc,type,severity,sa,name,category,cleared"
    assert list(logs.glob(f"report-{VIN}-*.txt"))


def test_LAP_13_inventory_export_writes_csv_offline(logger: Any, tmp_path: Path) -> None:
    s, fc, t = logger
    logs = tmp_path / "logs"
    ctl(t, "--folder", str(logs), "retrieve")
    out = tmp_path / "inv.csv"
    argv = ["inventory", "export", "--from-folder", str(logs / VIN), "--out", str(out)]
    assert main(argv, transport=None, out=io.StringIO()) == EXIT_OK  # offline: no logger
    rows = out.read_text("utf-8").splitlines()
    assert rows[0].startswith("entry,name,category") and rows[1].startswith("E01,")
    assert "ECU from training" in rows[1]


def test_LAP_9_the_open_session_is_copied_as_complete_records(logger: Any, tmp_path: Path) -> None:
    s, fc, t = logger
    newest = sorted((t.card / "sessions").iterdir())[-1]

    class MidWrite(Local):
        def fetch(self, remote: str, local: Path) -> None:
            super().fetch(remote, local)
            if remote == f"sessions/{newest.name}":
                with open(local, "ab") as fh:
                    fh.write(b'{"rec": 99, "type": "half')  # copied while a record was written

    t = MidWrite(s, t.card)
    logs = tmp_path / "logs"
    code, text = ctl(t, "--folder", str(logs), "retrieve")
    assert code == EXIT_OK and "open session in progress" in text
    copy = (logs / VIN / "sessions" / newest.name).read_bytes()
    assert copy.endswith(b"\n") and b'"rec": 99' not in copy


def test_LAP_8_each_header_lists_the_installed_operator_key_fingerprints(tmp_path: Path) -> None:
    from j1939logger.j1939cmd import fingerprint
    from j1939logger.session import operator_key_fingerprints

    keys = tmp_path / "keys"
    keys.mkdir()
    blob = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
    (keys / "jdoe.pub").write_text(f"ssh-ed25519 {blob} jdoe@laptop\n", "ascii")
    (keys / "notes.pub").write_text("not a key\n", "ascii")
    assert operator_key_fingerprints(keys) == [fingerprint(f"publickey ssh-ed25519 {blob}")]
