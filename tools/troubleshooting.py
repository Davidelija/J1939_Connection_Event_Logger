#!/usr/bin/env python3
"""troubleshooting: generate the user manual's troubleshooting table from docs/errors.md (DC-22).

CLAUDE.md rule 11: the troubleshooting table is generated from
``docs/errors.md``. Each error row becomes one manual row: the light, what
happened (source and error), what the logger does (its action, and the
transmit state when it changes) and what to do (the Operator column). The
table is written between ``<!-- troubleshooting:start -->`` and
``<!-- troubleshooting:end -->`` in ``docs/user-manual.md``.

    python tools/troubleshooting.py            # rewrite the table in the manual
    python tools/troubleshooting.py --check    # exit 1 if the manual is out of date (CI)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- troubleshooting:start -->"
END = "<!-- troubleshooting:end -->"
HEADER = [
    "Light",
    "What happened",
    "What the logger does",
    "What to do",
]
UNCHANGED_TRANSMIT = {"continues", "n/a", ""}


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(errors_md: str) -> list[dict[str, str]]:
    """The error rows of docs/errors.md, by column name."""
    lines = [ln for ln in errors_md.splitlines() if ln.startswith("|")]
    header: Optional[list[str]] = None
    out = []
    for ln in lines:
        cells = _cells(ln)
        if header is None:
            if cells[:2] == ["Source", "Error"]:
                header = cells
            continue
        if set("".join(cells)) <= set("- "):
            continue  # the separator row
        if len(cells) != len(header):
            raise ValueError(f"row has {len(cells)} cells, header {len(header)}: {ln[:60]}")
        out.append(dict(zip(header, cells)))
    if header is None or "Operator" not in header:
        raise ValueError("docs/errors.md has no table with an Operator column")
    return out


def table(errors_md: str) -> str:
    """The troubleshooting table in Markdown."""
    out = ["| " + " | ".join(HEADER) + " |", "| " + " | ".join("---" for _ in HEADER) + " |"]
    for r in rows(errors_md):
        does = r["Action"].rstrip()
        if r["Transmit"].lower() not in UNCHANGED_TRANSMIT:
            stop = "" if does.endswith(".") else "."
            does += f"{stop} Transmit: {r['Transmit'].rstrip('.').lower()}."
        if not r["Operator"]:
            raise ValueError(f"no Operator text for {r['Source']}: {r['Error'][:40]}")
        out.append(f"| {r['Light']} | {r['Source']}: {r['Error']} | {does} | {r['Operator']} |")
    return "\n".join(out) + "\n"


def render(manual: str, errors_md: str) -> str:
    """The manual with its troubleshooting table replaced."""
    if manual.count(START) != 1 or manual.count(END) != 1:
        raise ValueError(f"the manual needs one {START} and one {END}")
    head, rest = manual.split(START, 1)
    _, tail = rest.split(END, 1)
    note = (
        "*Generated from `docs/errors.md` by `tools/troubleshooting.py`; "
        "edit that table, not this one.*\n\n"
    )
    return f"{head}{START}\n{note}{table(errors_md)}{END}{tail}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the manual is out of date")
    ap.add_argument("--errors", type=Path, default=ROOT / "docs" / "errors.md")
    ap.add_argument("--manual", type=Path, default=ROOT / "docs" / "user-manual.md")
    args = ap.parse_args(argv)
    manual = args.manual.read_text(encoding="utf-8")
    try:
        new = render(manual, args.errors.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"troubleshooting: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if new != manual:
            print("troubleshooting: docs/user-manual.md is out of date; run "
                  "python tools/troubleshooting.py", file=sys.stderr)  # fmt: skip
            return 1
        print("troubleshooting: the manual's table matches docs/errors.md")
        return 0
    if new != manual:
        with open(args.manual, "w", encoding="utf-8", newline="\n") as fh:  # Python 3.9
            fh.write(new)
        print("troubleshooting: table updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
