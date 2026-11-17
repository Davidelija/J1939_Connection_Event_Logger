"""cmdserver, j1939cmd and main (step 7 PR 2, DC-21): the socket, operator keys, service down."""

from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import threading
import time
import weakref
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from j1939logger.cmdserver import CmdServer, check, request
from j1939logger.j1939cmd import (
    EXIT_BAD_INPUT,
    EXIT_NOT_RUNNING,
    EXIT_OK,
    EXIT_REFUSED,
    fingerprint,
    operator_for,
    run,
)
from j1939logger.j1939cmd import main as j1939cmd_main
from j1939logger.main import inventory_from_file
from j1939logger.main import main as logger_main
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.session import Session, settings_from_config
from j1939logger.types import Frame

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)
needs_unix = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs Unix sockets")


# Frames reach the logger through the platform's frame feed (DC-27), not capture's internals.
_BUS: weakref.WeakKeyDictionary[Session, DesktopPlatform] = weakref.WeakKeyDictionary()


def put(s: Session, *frames: Frame, drops: Optional[int] = None) -> None:
    """Put frames on the bus; returns once capture has taken them in."""
    _BUS[s].feed(list(frames), drops)


class Bus(DesktopPlatform):
    def __init__(self, **kw: Any) -> None:
        super().__init__(feed=True, **kw)  # frames come through the feed (DC-27)

    def bitrate_check(self) -> Optional[int]:
        return 250000


_STARTED: list[Session] = []  # stopped after each test (QC-4 E3: no sync thread left running)


@pytest.fixture(autouse=True)
def _stop_sync_threads() -> Iterator[None]:
    yield
    while _STARTED:
        s = _STARTED.pop()
        if s.eventlog is not None:
            s.eventlog.stop_sync()


def session(root: Path) -> tuple[Session, FakeClock]:
    fc = FakeClock(start_utc=START, start_mono=100.0)
    settings = settings_from_config(json.loads((EXAMPLES / "cfg-v3.json").read_text("utf-8")))
    inv = inventory_from_file(json.loads((EXAMPLES / "inv-v2.json").read_text("utf-8")))
    bus = Bus(clock=fc, root=root)
    s = Session(bus, settings, inv, {"config": "cfg-v3"}, None)
    _BUS[s] = bus
    _STARTED.append(s)
    s.start()
    put(s, Frame(1.7e9 + 100, 100.0, 0x0CF00400, True, False, False, bytes(8), False))
    for _ in range(30):
        s.step()
        fc.advance(0.1)
    return s, fc


def pump(s: Session, fc: FakeClock, done: threading.Event) -> None:
    while not done.is_set():
        put(s, Frame(1.7e9 + fc.mono(), fc.mono(), 0x0CF00400, True, False, False,
                                bytes(8), False))  # fmt: skip
        s.step()
        fc.advance(0.05)
        time.sleep(0.002)


# -- cmdserver (STS-23) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("req", "error"),
    [
        ([1, 2], "the request is not a JSON object"),
        ({"proto": 2, "cmd": "status"}, "unknown protocol version 2; the logger speaks 1"),
        ({"proto": 1, "cmd": "wipe"}, "unknown command 'wipe'"),
        ({"proto": 1, "cmd": "status", "args": [1]}, "args must be a JSON object"),
    ],
)
def test_STS_23_bad_requests_are_refused_with_the_next_step(req: Any, error: str) -> None:
    reply = check(req)
    assert reply is not None and reply["ok"] is False and reply["error"] == error
    assert reply["next"]


def test_STS_23_commands_are_answered_in_the_main_loop(tmp_path: Path) -> None:
    s, fc = session(tmp_path)
    server = CmdServer(tmp_path / "cmd.sock", s)
    done = threading.Event()
    t = threading.Thread(target=pump, args=(s, fc, done))
    t.start()
    try:
        reply = server.submit({"proto": 1, "cmd": "status"})
        assert reply["ok"] and reply["result"]["state"] in ("recording", "starting")
        login = server.submit({"proto": 1, "cmd": "login", "operator": "jdoe"})
        assert login["ok"] and login["result"] == {"operator": "jdoe"}
    finally:
        done.set()
        t.join()


def test_STS_23_a_second_command_at_the_same_time_is_refused_as_busy(tmp_path: Path) -> None:
    s, _ = session(tmp_path)
    server = CmdServer(tmp_path / "cmd.sock", s)
    server._busy.acquire()  # another operator's command is waiting
    reply = server.submit({"proto": 1, "cmd": "status"})
    assert (reply["ok"], reply["error"]) == (False, "another command is running")


@needs_unix
def test_STS_23_requests_over_the_unix_socket(tmp_path: Path) -> None:
    s, fc = session(tmp_path)
    path = tmp_path / "run" / "cmd.sock"
    server = CmdServer(path, s)
    server.start()
    done = threading.Event()
    t = threading.Thread(target=pump, args=(s, fc, done))
    t.start()
    try:
        reply = request(path, {"proto": 1, "cmd": "status"})
        assert reply["ok"] is True and reply["proto"] == 1
        bad = request(path, {"proto": 9, "cmd": "status"})
        assert bad["ok"] is False and "protocol" in bad["error"]
    finally:
        done.set()
        t.join()
        server.stop()
    assert not path.exists()


# -- j1939cmd (STS-5, STS-23 (d), LAP-15) ---------------------------------------------


def test_STS_5_fingerprint_matches_ssh_keygen(tmp_path: Path) -> None:
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        pytest.skip("needs ssh-keygen")
    key = tmp_path / "op"
    subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    pub = (tmp_path / "op.pub").read_text("ascii").split()
    listed = subprocess.run([keygen, "-lf", str(key) + ".pub"], check=True,
                            capture_output=True, text=True).stdout.split()[1]  # fmt: skip
    auth = f"publickey {pub[0]} {pub[1]}\n"
    assert fingerprint(auth) == listed


def test_STS_5_operator_names_come_from_the_fingerprint_file() -> None:
    text = "# keys.sh\nSHA256:abc jdoe\n\nSHA256:def  asmith  # night shift\n"
    assert operator_for("SHA256:abc", text) == "jdoe"
    assert operator_for("SHA256:def", text) == "asmith"
    assert operator_for("SHA256:zzz", text) is None and operator_for(None, text) is None
    assert fingerprint("password\n") is None


def test_STS_5_an_unknown_key_cannot_change_the_logger(tmp_path: Path) -> None:
    def send(path: Path, msg: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("must not be sent")

    reply, code = run('{"cmd": "clear", "args": {"events": ["1-5"]}}', operator=None,
                      socket_path=tmp_path / "s", card=None, send=send)  # fmt: skip
    assert code == EXIT_REFUSED and reply["error"] == "this SSH key is not an operator key"


def test_STS_23_requests_carry_the_operator_and_reason(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def send(path: Path, msg: dict[str, Any]) -> dict[str, Any]:
        seen.append(msg)
        return {"proto": 1, "ok": False, "error": "a reason is required", "next": "add --reason"}

    reply, code = run('{"cmd": "restart", "reason": "RO 9"}', operator="jdoe",
                      socket_path=tmp_path / "s", card=None, send=send)  # fmt: skip
    assert seen == [
        {"proto": 1, "cmd": "restart", "args": {}, "operator": "jdoe", "reason": "RO 9"}
    ]
    assert code == EXIT_REFUSED and reply["error"] == "a reason is required"
    assert run("not json", operator="jdoe", socket_path=tmp_path, card=None)[1] == EXIT_BAD_INPUT


def test_STS_23_when_the_service_is_down_only_status_and_retrieve_work(tmp_path: Path) -> None:
    card = tmp_path / "card"
    (card / "sessions").mkdir(parents=True)
    (card / "sessions" / "s000001_x.jsonl").write_text('{"rec":1}\n', "utf-8")
    (card / "status.json").write_text(json.dumps({"format": "status-1", "state": "recording"}))

    def down(path: Path, msg: dict[str, Any]) -> dict[str, Any]:
        raise ConnectionRefusedError

    status, code = run('{"cmd": "status"}', operator=None, socket_path=tmp_path, card=card,
                       send=down)  # fmt: skip
    assert code == EXIT_OK and status["result"]["service"] == "not running"
    listing, code = run('{"cmd": "retrieve_list"}', operator="jdoe", socket_path=tmp_path,
                        card=card, send=down)  # fmt: skip
    assert code == EXIT_OK and [f["path"] for f in listing["result"]["files"]] == [
        "sessions/s000001_x.jsonl"
    ]
    refused, code = run('{"cmd": "clear", "args": {"events": ["1-5"]}}', operator="jdoe",
                        socket_path=tmp_path, card=card, send=down)  # fmt: skip
    assert code == EXIT_NOT_RUNNING and refused["error"] == "logger not running"
    assert refused["next"]


def test_STS_5_j1939cmd_reads_the_key_from_ssh_user_auth(tmp_path: Path) -> None:
    auth = tmp_path / "auth"
    key = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
    auth.write_text(f"publickey ssh-ed25519 {key}\n")
    fp = fingerprint(auth.read_text())
    ops = tmp_path / "operators"
    ops.write_text(f"{fp} jdoe\n")
    out = io.StringIO()
    code = j1939cmd_main(["--socket", str(tmp_path / "none.sock"), "--operators", str(ops)],
                         stdin=io.StringIO('{"cmd": "train_start"}\n'), stdout=out,
                         environ={"SSH_USER_AUTH": str(auth)})  # fmt: skip
    reply = json.loads(out.getvalue())
    assert code == EXIT_NOT_RUNNING and reply["error"] == "logger not running"  # not the key


# -- main (DC-21 item 7) ----------------------------------------------------------------


def test_STS_9_main_seeds_an_empty_card_from_the_files_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Session, "run", lambda self, idle_s=0.01: None)  # do not loop
    code = logger_main(["--config", str(EXAMPLES / "cfg-v3.json"), "--inventory",
                        str(EXAMPLES / "inv-v2.json"), "--root", str(tmp_path),
                        "--interface", "nonexistent9"])  # fmt: skip
    assert code == 0  # a missing CAN interface no longer stops the logger (can_missing)
    assert (tmp_path / "card" / "config" / "cfg-v3.json").exists()
    assert (tmp_path / "card" / "inventory" / "inv-v2.json").exists()


def test_STS_19_main_without_any_config_stops_with_exit_code_2(tmp_path: Path) -> None:
    assert logger_main(["--root", str(tmp_path)]) == 2


def test_STS_23_an_over_long_socket_path_is_a_clear_startup_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from j1939logger.cmdserver import check_path

    long_path = tmp_path / ("x" * 120) / "cmd.sock"
    problem = check_path(long_path)
    assert problem is not None and ("limit is 107" in problem or "not available" in problem)
    seen: list[Any] = []

    def no_loop(self: Session, idle_s: float = 0.01) -> None:
        seen.append(self)

    monkeypatch.setattr(Session, "run", no_loop)
    code = logger_main(["--config", str(EXAMPLES / "cfg-v3.json"), "--root", str(tmp_path),
                        "--interface", "nonexistent9", "--socket", str(long_path)])  # fmt: skip
    assert code == 0  # no crash
    [s] = seen
    assert any(isinstance(f, tuple) and f[0].startswith("command socket not started")
               for f in s._startup_faults)  # fmt: skip


def test_LAP_5_retrieve_list_hashes_files_in_chunks(tmp_path: Path) -> None:
    import hashlib

    from j1939logger.session import card_files

    (tmp_path / "raw").mkdir()
    big = bytes(range(256)) * 9000  # over two 1 MiB chunks
    (tmp_path / "raw" / "s000001_c1_e1.log").write_bytes(big)
    [entry] = card_files(tmp_path)
    assert entry == {"path": "raw/s000001_c1_e1.log", "size": len(big),
                     "sha256": hashlib.sha256(big).hexdigest()}  # fmt: skip
