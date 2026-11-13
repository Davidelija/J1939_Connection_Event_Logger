"""tools/verify_chain.py (LOG-14, LOG-19): chain checks over real session files."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from j1939logger.clock import Clock
from j1939logger.eventlog import ZERO_HASH, EventLog
from j1939logger.eventlog import record_hash as logger_hash
from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.types import Record

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "docs" / "examples" / "s000142_20261106T140211Z.jsonl"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_chain", ROOT / "tools" / "verify_chain.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vc = _load()
START = datetime(2026, 11, 6, 14, 2, 11, tzinfo=timezone.utc)


def header(session: int, part: int = 1, new_card: bool = False, fmt: str = "log-1") -> Record:
    fields = {"format": fmt, "session": session, "part": part, "new_card": new_card}
    return Record("session_start", "info", START, None, fields)


def write_sessions(folder: Path, n: int = 2, prev: str = ZERO_HASH) -> list[Path]:
    """n chained sessions of 4 records each, written by the logger's eventlog."""
    fc = FakeClock(start_utc=START)
    platform = DesktopPlatform(clock=fc, root=folder / "root")
    clock = Clock(platform, 5)
    paths = []
    for s in range(1, n + 1):
        path = folder / f"s{s:06d}_20261106T140211Z.jsonl"
        log = EventLog(platform, clock, path, s, prev)
        log.append(header(s))
        log.append(Record("connection_start", "high", START, None, {"sa": 249}, conn=1))
        log.append(Record("time_sync", "info", START, None, {"source_sa": 0, "offset_s": 0.05}))
        log.append(Record("session_end", "info", START, None, {"reason": "key-off, bus silent"}))
        log.close()
        prev = log.last_hash
        paths.append(path)
    return paths


def lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines(keepends=True)


def test_LOG_14_session_142_example_verifies() -> None:
    report = vc.verify([EXAMPLE])
    assert report.ok and report.records == 15
    assert any("chain starts from" in n.message for n in report.notes)


def test_LOG_14_two_sessions_verify_as_one_chain(tmp_path: Path) -> None:
    write_sessions(tmp_path)
    report = vc.verify([tmp_path])
    assert report.ok, report.problems
    assert (report.files, report.records) == (2, 8)
    assert report.notes == []


def test_LOG_14_deleted_record_is_named_as_missing(tmp_path: Path) -> None:
    first, _ = write_sessions(tmp_path)
    content = lines(first)
    first.write_bytes(b"".join(content[:1] + content[2:]))  # delete rec 2
    report = vc.verify([tmp_path])
    assert not report.ok
    assert report.problems[0].message == "missing record(s) 2 to 2 before this line"
    assert report.problems[0].line == 2


def test_LOG_14_changed_record_is_named(tmp_path: Path) -> None:
    first, _ = write_sessions(tmp_path)
    content = lines(first)
    content[2] = content[2].replace(b'"source_sa":0', b'"source_sa":3')
    first.write_bytes(b"".join(content))
    report = vc.verify([tmp_path])
    assert not report.ok
    assert (report.problems[0].line, report.problems[0].message) == (
        3,
        "record content does not match its hash (changed)",
    )


def test_LOG_14_deleted_session_file_breaks_the_chain(tmp_path: Path) -> None:
    write_sessions(tmp_path, n=3)[1].unlink()
    report = vc.verify([tmp_path])
    assert not report.ok and "chain broken" in report.problems[0].message


def test_LOG_14_truncated_last_line_is_reported_not_broken(tmp_path: Path) -> None:
    _, second = write_sessions(tmp_path)
    second.write_bytes(second.read_bytes() + b'{"rec":5,"type":"conn')
    report = vc.verify([tmp_path])
    assert report.ok
    assert any(n.message.startswith("truncated last line (21 bytes)") for n in report.notes)


def test_LOG_5_new_card_is_a_declared_break_not_a_failure(tmp_path: Path) -> None:
    write_sessions(tmp_path, n=1)
    fc = FakeClock(start_utc=START)
    platform = DesktopPlatform(clock=fc, root=tmp_path / "root2")
    log = EventLog(
        platform, Clock(platform, 5), tmp_path / "s000002_20261107T080000Z.jsonl", 2, ZERO_HASH
    )
    log.append(header(2, new_card=True))
    log.append(Record("session_end", "info", START, None, {"reason": "key-off, bus silent"}))
    log.close()
    report = vc.verify([tmp_path])
    assert report.ok, report.problems
    assert any(n.message == "declared chain break: new card" for n in report.notes)


def test_LOG_14_laptop_last_hash_must_be_continued(tmp_path: Path) -> None:
    write_sessions(tmp_path)
    assert vc.verify([tmp_path], last_hash=ZERO_HASH).ok
    report = vc.verify([tmp_path], last_hash="f" * 64)
    assert not report.ok


def test_LOG_2_parts_are_checked_in_order_with_continuing_record_numbers(tmp_path: Path) -> None:
    fc = FakeClock(start_utc=START)
    platform = DesktopPlatform(clock=fc, root=tmp_path / "root")
    p1 = tmp_path / "s000007_20261106T140211Z.jsonl"
    p2 = tmp_path / "s000007_20261106T140211Z_p2.jsonl"
    log = EventLog(platform, Clock(platform, 5), p1, 7, ZERO_HASH)
    log.append(header(7))
    log.append(Record("session_end", "info", START, None, {"reason": "session roll-over"}))
    log.roll_over(p2)
    log.append(header(7, part=2))
    log.append(Record("session_end", "info", START, None, {"reason": "key-off, bus silent"}))
    log.close()
    assert [p.name for p in vc.order([tmp_path])] == [p1.name, p2.name]
    assert vc.verify([tmp_path]).ok


def test_LOG_19_unknown_format_is_refused(tmp_path: Path) -> None:
    fc = FakeClock(start_utc=START)
    platform = DesktopPlatform(clock=fc, root=tmp_path / "root")
    log = EventLog(platform, Clock(platform, 5), tmp_path / "s000001_x.jsonl", 1, ZERO_HASH)
    log.append(header(1, fmt="log-9"))
    log.close()
    assert vc.main([str(tmp_path / "s000001_x.jsonl")]) == 2


def test_LAP_9_open_session_is_reported_as_in_progress(tmp_path: Path) -> None:
    _, second = write_sessions(tmp_path)
    second.write_bytes(b"".join(lines(second)[:-1]))  # no session_end yet
    report = vc.verify([tmp_path])
    assert report.ok
    assert any("no session_end" in n.message for n in report.notes)


def test_LOG_14_verifier_hash_matches_the_logger(tmp_path: Path) -> None:
    body: dict[str, Any] = {"rec": 1, "type": "fault", "cause": "café ✓", "n": 1.25}
    assert vc.record_hash(ZERO_HASH, body) == logger_hash(ZERO_HASH, body)


def test_LOG_14_cli_exit_codes_and_json(tmp_path: Path, capsys: Any) -> None:
    first, _ = write_sessions(tmp_path)
    assert vc.main([str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["records"] == 8
    first.write_bytes(b"".join(lines(first)[1:]))
    assert vc.main([str(tmp_path)]) == 1
