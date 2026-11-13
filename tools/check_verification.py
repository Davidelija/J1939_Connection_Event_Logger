#!/usr/bin/env python3
"""Verification coverage check (DC-2; docs/verification.md, docs/test-plan.md section 10).

Modes:

``staged`` (every push)
    Each requirement whose Method includes T, that is not Deferred, and whose
    Step has merged must name a test in its Test-or-procedure cell. A test
    counts when its name starts with the row's requirement ID
    (``test_DET_1_...``) and a test function with that name exists under
    ``tests/``. A name ending in ``*`` matches by prefix. For step 8 rows a
    ``bench/`` procedure ID (A1 to A8, B-HW1, B-HW3, B-PLT2, B-STS20, B-SN1,
    or a ``bench/`` path) also counts.

``release`` (before a tag)
    Every non-deferred T row needs a passing test (Result starts with
    "pass"), a procedure with a result, or a recorded gap (Where "not
    verified", or Result "not supported ..." with the reason). Also fails
    while any ``docs/errors.md`` row still has a placeholder in its Test
    column (docs/handoff.md, Testing).

Merged steps come from the ``**Merged build steps:**`` line in
docs/verification.md (``none`` or a comma-separated list such as ``1, 2``),
or from ``--merged``. Exit code 0 when the check passes, 1 when it fails.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
BENCH_ID = re.compile(r"\bA[1-8]\b|\bB-[A-Z]+\d+\b|bench/")
TEST_NAME = re.compile(r"\btest_\w+\*?")
# The value runs to the first full stop or note, e.g. "**Merged build steps:** 1, 2. *(note)*".
MERGED_LINE = re.compile(r"^\*\*Merged build steps:\*\*\s*([^.*(\n]+)", re.MULTILINE)


@dataclass
class Row:
    req: str
    method: set[str]
    steps: list[str]
    test: str
    where: str
    result: str
    line: int

    @property
    def deferred(self) -> bool:
        return self.steps == ["—"] or self.test.lower().startswith("deferred")

    @property
    def is_t(self) -> bool:
        return "T" in self.method


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_matrix(text: str) -> list[Row]:
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 6 or not re.fullmatch(r"[A-Z]+-\d+[a-z]?", cells[0]):
            continue
        rows.append(
            Row(
                req=cells[0],
                method={m.strip() for m in cells[1].split(",")},
                steps=[s.strip() for s in cells[2].split("/")],
                test=cells[3],
                where=cells[4],
                result=cells[5],
                line=n,
            )
        )
    return rows


def parse_merged(text: str) -> set[str]:
    m = MERGED_LINE.search(text)
    if not m:
        raise ValueError("docs/verification.md has no '**Merged build steps:**' line")
    value = m.group(1).strip()
    if value.lower() == "none":
        return set()
    return {s.strip() for s in value.split(",") if s.strip()}


def collect_tests(tests_dir: Path) -> set[str]:
    names: set[str] = set()
    for path in tests_dir.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    names.add(node.name)
    return names


def _prefix(req: str) -> str:
    return "test_" + req.replace("-", "_") + "_"


def has_test(row: Row, tests: set[str]) -> bool:
    prefix = _prefix(row.req)
    for token in TEST_NAME.findall(row.test):
        if not token.startswith(prefix):
            continue
        if token.endswith("*"):
            if any(t.startswith(token[:-1]) for t in tests):
                return True
        elif token in tests:
            return True
    return False


def has_bench(row: Row) -> bool:
    return "8" in row.steps and bool(BENCH_ID.search(row.test))


def check_staged(rows: Sequence[Row], merged: set[str], tests: set[str]) -> list[str]:
    errors = []
    for row in rows:
        if not row.is_t or row.deferred or row.steps[0] not in merged:
            continue
        if not (has_test(row, tests) or has_bench(row)):
            errors.append(
                f"{row.req} (line {row.line}): T requirement of merged step {row.steps[0]} "
                f"names no existing test starting with {_prefix(row.req)}"
                + (" or bench/ procedure" if "8" in row.steps else "")
            )
    return errors


def _gap(row: Row) -> bool:
    return row.where.lower().startswith("not verified") or row.result.lower().startswith(
        "not supported"
    )


def check_release(rows: Sequence[Row], tests: set[str], errors_md: Optional[str]) -> list[str]:
    errors = []
    for row in rows:
        if not row.is_t or row.deferred:
            continue
        if _gap(row) and row.result:
            continue
        if has_test(row, tests) and row.result.lower().startswith("pass"):
            continue
        if has_bench(row) and row.result:
            continue
        errors.append(
            f"{row.req} (line {row.line}): needs a passing test, a procedure with a result, "
            "or a recorded gap"
        )
    if errors_md is not None:
        for n, line in enumerate(errors_md.splitlines(), 1):
            cells = _cells(line) if line.startswith("|") else []
            if len(cells) == 10 and cells[2].startswith("`"):
                test = cells[9]
                if not test or re.fullmatch(r"\*?\(step [0-9a-z]+\)\*?", test):
                    errors.append(f"docs/errors.md line {n} ({cells[2]}): Test column placeholder")
    return errors


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("staged", "release"), default="staged")
    ap.add_argument("--matrix", type=Path, default=ROOT / "docs" / "verification.md")
    ap.add_argument("--errors", type=Path, default=ROOT / "docs" / "errors.md")
    ap.add_argument("--tests", type=Path, default=ROOT / "tests")
    ap.add_argument("--merged", help="comma-separated merged steps; overrides the matrix line")
    args = ap.parse_args(argv)

    text = args.matrix.read_text(encoding="utf-8")
    rows = parse_matrix(text)
    tests = collect_tests(args.tests) if args.tests.exists() else set()
    if args.mode == "staged":
        merged = (
            {s.strip() for s in args.merged.split(",") if s.strip()}
            if args.merged is not None
            else parse_merged(text)
        )
        errors = check_staged(rows, merged, tests)
        label = f"staged (merged steps: {', '.join(sorted(merged)) or 'none'})"
    else:
        errors_md = args.errors.read_text(encoding="utf-8") if args.errors.exists() else None
        errors = check_release(rows, tests, errors_md)
        label = "release"

    by_req: dict[str, int] = {}
    for row in rows:
        by_req[row.req] = by_req.get(row.req, 0) + 1
    dupes = sorted(r for r, n in by_req.items() if n > 1)
    errors += [f"{r}: more than one row in the matrix" for r in dupes]

    for e in errors:
        print(f"FAIL {e}")
    print(f"check_verification {label}: {len(rows)} rows, {len(errors)} failures")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
