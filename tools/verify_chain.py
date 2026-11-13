#!/usr/bin/env python3
"""verify_chain: check the hash chain across a set of session files (LOG-14).

docs/modules.md section 4 (verify_chain, contract v1, frozen for step 2). A
standalone tool with no dependency on the logger package: the maintenance
laptop and the tests run it the same way.

    python tools/verify_chain.py FOLDER_OR_FILES... [--last-hash HASH] [--json]

Checks, in session and part order (``sNNNNNN_<start>[_pN].jsonl``):

* every line is one JSON record whose ``hash`` is the SHA-256 of ``prev``
  followed by the record without ``hash`` (compact JSON, keys as written,
  non-ASCII as-is; docs/log-format.md);
* each ``prev`` is the previous record's hash, across lines, parts and
  sessions; with ``--last-hash`` (the laptop's last retrieved hash) the first
  record must continue from it;
* record numbers run on without gaps within a session, across its parts
  (DC-11), so a deleted record is named as missing, not just as a break;
* every ``session_start`` carries a format this tool knows (``log-1``); an
  unknown format is refused (LOG-19).

Reported but not failures:

* a replacement card: a first record with ``prev`` of 64 zeros and
  ``new_card: true`` in ``session_start`` is a declared chain break (LOG-5);
* an incomplete last line after a power loss is reported as truncated, never
  as broken (LOG-5, LOG-14);
* a newest session with no ``session_end`` is in progress or ended without
  one (LAP-9).

Exit code 0 when the chain verifies, 1 when it is broken, 2 for an unknown
format or unreadable input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

KNOWN_FORMATS = ("log-1",)
ZERO = "0" * 64
_NAME = re.compile(r"^s(\d{6})_([0-9TZ]+|noclock)(?:_p(\d+))?\.jsonl$")


@dataclass
class Problem:
    file: str
    line: int
    rec: Optional[int]
    message: str


@dataclass
class Report:
    ok: bool = True
    unknown_format: bool = False
    records: int = 0
    files: int = 0
    last_hash: Optional[str] = None
    problems: list[Problem] = field(default_factory=list)
    notes: list[Problem] = field(default_factory=list)

    def fail(self, p: Problem) -> None:
        self.ok = False
        self.problems.append(p)


def record_hash(prev: str, body: dict[str, Any]) -> str:
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev + text).encode("utf-8")).hexdigest()


def order(paths: Sequence[Path]) -> list[Path]:
    """Session files in session and part order; a folder is expanded to its session files."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += [q for q in p.iterdir() if _NAME.match(q.name)]
        else:
            files.append(p)

    def key(p: Path) -> tuple[int, int, str]:
        m = _NAME.match(p.name)
        return (int(m.group(1)), int(m.group(3) or 1), p.name) if m else (10**9, 0, p.name)

    return sorted(files, key=key)


def verify(paths: Sequence[Path], last_hash: Optional[str] = None) -> Report:
    report = Report()
    files = order([Path(p) for p in paths])
    report.files = len(files)
    prev: Optional[str] = last_hash
    next_rec: Optional[int] = None
    session: Optional[int] = None
    last_type: Optional[str] = None
    for fi, path in enumerate(files):
        name = path.name
        try:
            data = path.read_bytes()
        except OSError as exc:
            report.fail(Problem(name, 0, None, f"cannot read: {exc}"))
            continue
        lines = data.split(b"\n")
        tail = lines.pop()  # b"" when the file ends with a newline
        if tail:
            last_file = fi == len(files) - 1
            report.notes.append(
                Problem(name, len(lines) + 1, None, f"truncated last line ({len(tail)} bytes)")
            )
            if not last_file:
                report.notes.append(
                    Problem(name, len(lines) + 1, None, "truncated line is not in the newest file")
                )
        for n, raw in enumerate(lines, 1):
            try:
                rec = json.loads(raw)
                if not isinstance(rec, dict) or not isinstance(rec.get("hash"), str):
                    raise ValueError("not a record")
            except ValueError:
                report.fail(Problem(name, n, None, "line is not a valid record"))
                prev, next_rec = None, None
                continue
            report.records += 1
            r = rec.get("rec")
            if n == 1:
                if rec.get("type") != "session_start":
                    report.fail(
                        Problem(
                            name, n, r, "file does not start with session_start (records missing)"
                        )
                    )
                elif rec.get("part", 1) == 1 and r != 1:
                    report.fail(
                        Problem(
                            name, n, r, f"session starts at record {r}, not 1 (records missing)"
                        )
                    )
            if rec.get("type") == "session_start":
                fmt = rec.get("format")
                if fmt not in KNOWN_FORMATS:
                    report.unknown_format = True
                    report.fail(
                        Problem(
                            name,
                            n,
                            r,
                            f"unknown format {fmt!r}; this verifier reads {KNOWN_FORMATS}",
                        )
                    )
                    return report
                if rec.get("session") != session:
                    session = rec.get("session")
                    next_rec = None
            body = {k: v for k, v in rec.items() if k != "hash"}
            if record_hash(str(rec.get("prev", "")), body) != rec["hash"]:
                report.fail(Problem(name, n, r, "record content does not match its hash (changed)"))
            if prev is not None and rec.get("prev") != prev:
                declared = (
                    rec.get("prev") == ZERO
                    and rec.get("type") == "session_start"
                    and rec.get("new_card") is True
                )
                if declared:
                    report.notes.append(Problem(name, n, r, "declared chain break: new card"))
                elif next_rec is not None and isinstance(r, int) and r > next_rec:
                    report.fail(
                        Problem(
                            name, n, r, f"missing record(s) {next_rec} to {r - 1} before this line"
                        )
                    )
                else:
                    report.fail(
                        Problem(
                            name, n, r, "prev does not match the previous record (chain broken)"
                        )
                    )
            elif prev is None and fi == 0 and n == 1 and last_hash is None:
                if rec.get("prev") != ZERO:
                    report.notes.append(Problem(name, n, r, f"chain starts from {rec.get('prev')}"))
            elif next_rec is not None and isinstance(r, int) and r != next_rec:
                report.fail(Problem(name, n, r, f"record number {r}, expected {next_rec}"))
            prev = rec["hash"]
            next_rec = r + 1 if isinstance(r, int) else None
            last_type = rec.get("type")
    if files and last_type != "session_end":
        report.notes.append(
            Problem(
                files[-1].name,
                0,
                None,
                "newest session has no session_end (in progress, or did not end cleanly)",
            )
        )
    report.last_hash = prev
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Verify the hash chain across session files (LOG-14).")
    ap.add_argument("paths", nargs="+", type=Path, help="session files or a folder of them")
    ap.add_argument(
        "--last-hash", help="the last hash retrieved before, which the chain must continue from"
    )
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    report = verify(args.paths, args.last_hash)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "files": report.files,
                    "records": report.records,
                    "last_hash": report.last_hash,
                    "problems": [p.__dict__ for p in report.problems],
                    "notes": [p.__dict__ for p in report.notes],
                },
                indent=2,
            )
        )
    else:
        for p in report.problems:
            print(
                f"BROKEN {p.file} line {p.line}"
                + (f" (rec {p.rec})" if p.rec else "")
                + f": {p.message}"
            )
        for p in report.notes:
            print(f"NOTE   {p.file}" + (f" line {p.line}" if p.line else "") + f": {p.message}")
        verdict = "chain verifies" if report.ok else "chain BROKEN"
        counts = f"{report.files} files, {report.records} records"
        print(f"{verdict}: {counts}, last hash {report.last_hash}")
    if report.unknown_format:
        return 2
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
