"""report: the five-section review report and events.csv (DC-21; STS-7, LAP-12, LAP-13, LAP-17).

Works on a retrieved folder (``<folder>/<VIN>/``) without a logger connection.

Sections, in order (STS-7): events to review; new devices with make and type;
changes to the inventory and config since the last retrieval, with operator
and reason (weakening config changes marked); sessions and gaps; the chain
check and the latest chain hash. Events are grouped by device (NAME, or SA for
a device without one) across sessions.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

from j1939ctl.retrieve import chain_checker

# Plain words for categories (LAP-17).
PLAIN = {
    "external device (unrecognized)": "new device",
    "vehicle ECU not in baseline": "ECU not in training",
    "trailer device": "trailer device",
    "external device (approved)": "approved device",
    "vehicle ECU in baseline": "ECU from training",
}
CHANGE_TYPES = ("approval", "rejection", "inventory_remove", "config_change", "config_rejected",
                "reset")  # fmt: skip
CSV_FIELDS = ["event", "session", "utc", "type", "severity", "sa", "name", "category", "cleared"]


def plain(category: Optional[str]) -> str:
    return PLAIN.get(category or "", category or "")


def load(folder: Path) -> list[dict[str, Any]]:
    """Every complete record in the folder's session files, with its event ID."""
    out = []
    files = sorted((folder / "sessions").glob("*.jsonl")) if (folder / "sessions").is_dir() else []
    for f in files:
        try:
            session = int(f.name[1:7])
        except ValueError:
            continue
        for line in f.read_text("utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            r["_session"] = session
            r["_event"] = f"{session}-{r.get('rec')}"
            out.append(r)
    return out


def cleared(records: Iterable[dict[str, Any]]) -> set[str]:
    done: set[str] = set()
    for r in records:
        if r.get("type") == "review_clear":
            done |= set(r.get("cleared") or [])
        if r.get("type") == "approval":
            done |= set(r.get("events_cleared") or [])
    return done


def device_key(r: dict[str, Any]) -> str:
    return str(r.get("name") or f"SA {r.get('sa')}")


def events_csv(records: list[dict[str, Any]]) -> str:
    done = cleared(records)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_FIELDS)
    for r in records:
        if r.get("type") in ("session_start", "session_end"):
            continue
        w.writerow([r["_event"], r["_session"], r.get("utc"), r.get("type"), r.get("sev"),
                    r.get("sa"), r.get("name"), plain(r.get("category")),
                    "yes" if r["_event"] in done else "no"])  # fmt: skip
    return buf.getvalue()


def build(folder: Path) -> str:
    """The report text (STS-7)."""
    records = load(folder)
    done = cleared(records)
    lines: list[str] = [f"Logger report for {folder.name}", ""]

    lines.append("1. Events to review")
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r.get("sev") == "high" and r["_event"] not in done:
            groups.setdefault(device_key(r), []).append(r)
    if not groups:
        lines.append("   none")
    for key, rs in groups.items():
        sessions = sorted({r["_session"] for r in rs})
        lines.append(f"   {key}: {len(rs)} event(s) in session(s) {', '.join(map(str, sessions))}")
        for r in rs:
            lines.append(f"     {r['_event']}  {r.get('utc')}  {r.get('type')}  "
                         f"{plain(r.get('category'))}".rstrip())  # fmt: skip
    lines.append("")

    lines.append("2. New devices")
    idents = {
        (r["_session"], r.get("conn")): r for r in records if r.get("type") == "identification"
    }
    starts = [r for r in records if r.get("type") == "connection_start"]
    if not starts:
        lines.append("   none")
    for r in starts:
        ident = idents.get((r["_session"], r.get("conn")), {})
        lines.append(f"   {r['_event']}  SA {r.get('sa')}  {r.get('name') or 'no NAME'}  "
                     f"{plain(r.get('category'))}; type {ident.get('type_guess') or 'unknown'}; "
                     f"make {ident.get('make') or 'unknown'}")  # fmt: skip
    lines.append("")

    lines.append("3. Changes since the last retrieval")
    last = max((i for i, r in enumerate(records) if r.get("type") == "retrieval"), default=-1)
    changes = [r for r in records[last + 1 :] if r.get("type") in CHANGE_TYPES]
    if not changes:
        lines.append("   none")
    for r in changes:
        mark = "  [WEAKENS DETECTION]" if r.get("weakens_detection") else ""
        what = r.get("kind") or r.get("mode") or r.get("removed") or r.get("new_version") or ""
        lines.append(f"   {r['_event']}  {r.get('type')} {what}  by {r.get('operator')}  "
                     f"reason: {r.get('reason') or '-'}{mark}")  # fmt: skip
    lines.append("   Reviewer sign-off: ____________________  date: __________")
    lines.append("")

    lines.append("4. Sessions and gaps")
    headers = [r for r in records if r.get("type") == "session_start"]
    numbers = sorted({r["_session"] for r in headers})
    for r in headers:
        lines.append(f"   session {r['_session']} part {r.get('part')}: software {r.get('sw')}, "
                     f"config {r.get('config')}, inventory {r.get('inventory')}")  # fmt: skip
    gaps = [n for n in range(numbers[0], numbers[-1] + 1) if n not in numbers] if numbers else []
    lines.append(f"   gaps: {', '.join(map(str, gaps)) if gaps else 'none'}")
    lines.append("")

    lines.append("5. Chain check")
    paths = sorted((folder / "sessions").glob("*.jsonl")) if (folder / "sessions").is_dir() else []
    rep = chain_checker().verify(paths, None)
    lines.append(
        f"   {'verified' if rep.ok else 'BROKEN'}: {rep.records} records in {rep.files} files"
    )
    for p in rep.problems:
        lines.append(f"   {p.file} line {p.line}: {p.message}")
    for n in rep.notes:
        lines.append(f"   note: {n.message}")
    lines.append(f"   latest chain hash: {rep.last_hash}")
    return "\n".join(lines) + "\n"


def inventory_csv(doc: dict[str, Any]) -> str:
    """The inventory as CSV (LAP-13): one row per entry."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["entry", "name", "category", "addresses", "make", "model", "pgns_sent",
                "requests_trained", "pgns_approved"])  # fmt: skip
    for e in doc.get("entries", []):
        approved = " ".join(f"{a.get('pgn')}:{a.get('kind')}" for a in e.get("pgns_approved", []))
        w.writerow([e.get("entry"), e.get("name"), plain(e.get("category")),
                    " ".join(map(str, e.get("addresses", []))), e.get("make"), e.get("model"),
                    " ".join(map(str, e.get("pgns_sent", []))),
                    " ".join(map(str, e.get("requests_trained", []))), approved])  # fmt: skip
    return buf.getvalue()


def newest_inventory(folder: Path) -> Optional[dict[str, Any]]:
    def number(p: Path) -> int:
        tail = p.stem.split("-v")[-1]
        return int(tail) if tail.isdigit() else 0

    files = sorted((folder / "inventory").glob("inv-v*.json"), key=number)
    if not files:
        return None
    data: dict[str, Any] = json.loads(files[-1].read_text("utf-8"))
    return data
