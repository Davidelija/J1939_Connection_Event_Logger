"""j1939ctl command line: the 16 commands (LAP-2), one prompt pattern (LAP-3), plain words (LAP-17).

    j1939ctl [--host HOST] [--folder DIR] [--yes] <command> ...

Every command that changes the logger shows in plain words what will change
(with a warning line for a risky change), asks for a reason (or takes
``--reason``), then asks y/N unless ``--yes`` is given (LAP-3). A refused command
says why and what to do, and exits non-zero (LAP-15): 1 refused or declined,
2 usage, 3 logger not reachable or not running.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TextIO

from j1939ctl import VERSION, report
from j1939ctl.retrieve import retrieve
from j1939ctl.transport import NOT_RUNNING, SshTransport, Transport
from j1939logger.config import Config, ConfigError, validate

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
DEFAULT_HOST = "192.168.250.1"  # network.address (STS-5)
DEFAULT_CARD = "/media/card"  # the Beacon's card mount, confirmed in step 8

Ask = Callable[[str], str]


class Ctl:
    def __init__(self, transport: Optional[Transport], out: TextIO, ask: Ask, yes: bool) -> None:
        self.t = transport
        self.out = out
        self.ask = ask
        self.yes = yes

    def say(self, text: str = "") -> None:
        self.out.write(text + "\n")

    def refused(self, reply: dict[str, Any], code: int = EXIT_REFUSED) -> int:
        self.say(f"Refused: {reply.get('error')}")
        if reply.get("next"):
            self.say(f"Next step: {reply['next']}")
        return NOT_RUNNING if code == NOT_RUNNING else EXIT_REFUSED

    def call(self, cmd: str, args: Optional[dict[str, Any]] = None,
             reason: Optional[str] = None) -> tuple[dict[str, Any], int]:  # fmt: skip
        assert self.t is not None
        return self.t.call(cmd, args, reason)

    def confirm(
        self, changes: list[str], warnings: list[str], reason: Optional[str]
    ) -> Optional[str]:
        """The one prompt pattern (LAP-3 (d), (e)); the reason, or None if declined."""
        self.say("This will:")
        for c in changes:
            self.say(f"  - {c}")
        for w in warnings:
            self.say(f"  WARNING: {w}")
        while not reason:
            reason = self.ask("Reason (for example a repair-order number): ").strip()
        if not self.yes and self.ask("Go ahead? y/N ").strip().lower() not in ("y", "yes"):
            self.say("Nothing changed.")
            return None
        return reason


def _when(utc: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(utc).replace("Z", "+00:00"))
    except ValueError:
        return None


# -- commands -----------------------------------------------------------------------------


def cmd_status(c: Ctl, a: argparse.Namespace) -> int:
    reply, code = c.call("status")
    if not reply.get("ok"):
        return c.refused(reply, code)
    s = reply["result"]
    c.say(f"State: {s.get('state')} (light {s.get('light')})")
    c.say(f"VIN: {s.get('vin') or 'not known yet'}    Session: {s.get('session')}")
    c.say(f"Events to review: {s.get('unreviewed_high', 0)}")
    c.say(f"Training needed: {'yes' if s.get('untrained') else 'no'}")
    full = " (nearly full)" if s.get("card_nearly_full") else ""
    c.say(f"Card use: {s.get('card_used_pct')}%{full}")
    logger_time = _when(s.get("utc"))
    if logger_time is not None:  # LAP-10: never sets the logger clock, only shows the difference
        diff = (logger_time - datetime.now(timezone.utc)).total_seconds()
        c.say(f"Clock: {'OK' if s.get('clock_valid') else 'not valid'} ({s.get('clock_source')}), "
              f"{diff:+.0f} s from this laptop")  # fmt: skip
    c.say(f"Versions: config {s.get('config')}, inventory {s.get('inventory')}, "
          f"library {s.get('library')}")  # fmt: skip
    if s.get("service") == "not running":
        c.say("The logger service is not running; this is the last saved status.")
    n = s.get("unreviewed_high", 0)
    if n:
        nxt = f"{n} event{'s' if n != 1 else ''} to review: run events"
    elif s.get("untrained"):
        nxt = "the logger needs training: run train start"
    else:
        nxt = "nothing to do; run retrieve to copy the logs"
    c.say(f"Next step: {nxt}")
    return EXIT_OK


def cmd_events(c: Ctl, a: argparse.Namespace) -> int:
    reply, code = c.call("events", {"all": a.all})
    if not reply.get("ok"):
        return c.refused(reply, code)
    rows = reply["result"]["events"]
    if not rows:
        c.say("No events to review.")
    for e in rows:
        what = report.plain(e.get("category")) or str(e.get("type")).replace("_", " ")
        who = e.get("name") or (f"SA {e['sa']}" if e.get("sa") is not None else "")
        extra = f" PGN {e['pgn']}" if e.get("pgn") is not None else ""
        c.say(f"{e['event']}  {e.get('utc')}  {what}  {who}{extra}"
              f"{'' if not e.get('reviewed') else '  (reviewed)'}")  # fmt: skip
    return EXIT_OK


def _event(c: Ctl, event_id: str) -> Optional[dict[str, Any]]:
    reply, _ = c.call("events", {"all": True})
    for e in (reply.get("result") or {}).get("events", []):
        if e["event"] == event_id:
            return dict(e)
    return None


def cmd_approve(c: Ctl, a: argparse.Namespace) -> int:
    e = _event(c, a.event)
    if e is None:
        return c.refused({"error": f"no event {a.event}", "next": "run events --all for the IDs"})
    warnings = []
    if e.get("type") == "known_device_new_pgn":
        cfg, _ = c.call("config_show")
        control = (
            ((cfg.get("result") or {}).get("config") or {})
            .get("detection", {})
            .get("control_pgns", [])
        )
        change = f"add PGN {e.get('pgn')} ({e.get('direction')}) to {e.get('entry')}"
        if e.get("pgn") in control:
            warnings.append(
                f"PGN {e.get('pgn')} is a control PGN; it will be counted but not flagged"
            )
    elif e.get("type") == "address_change":
        change = f"add the new address of {e.get('entry')} to the inventory"
    else:
        change = f"add the device at SA {e.get('sa')} ({e.get('name') or 'no NAME'}) as approved"
    reason = c.confirm([change, f"clear event {a.event}", "save a new inventory version, used "
                        "from the next session"], warnings, a.reason)  # fmt: skip
    if reason is None:
        return EXIT_REFUSED
    reply, code = c.call("approve", {"event": a.event, "warning_shown": bool(warnings)}, reason)
    if not reply.get("ok"):
        return c.refused(reply, code)
    c.say(f"Approved. New inventory {reply['result']['inventory']}; event {a.event} cleared.")
    return EXIT_OK


def cmd_remove(c: Ctl, a: argparse.Namespace) -> int:
    inv, _ = c.call("inventory_show")
    doc = (inv.get("result") or {}).get("inventory") or {}
    entry = next((e for e in doc.get("entries", []) if e.get("entry") == a.entry), None)
    if entry is None:
        return c.refused({"error": f"no entry {a.entry} in the inventory",
                          "next": "run inventory show for the entry IDs"})  # fmt: skip
    warnings = []
    trained = (entry.get("added") or {}).get("how") == "training"
    if a.pgn is None:
        change = f"remove {a.entry} ({report.plain(entry.get('category'))}) from the inventory"
        if trained:
            warnings.append(
                "this ECU was found in training; it will show as new when it next appears"
            )
    else:
        change = f"remove PGN {a.pgn} ({a.direction}) from {a.entry}"
    reason = c.confirm([change, "save a new inventory version, used from the next session"],
                       warnings, a.reason)  # fmt: skip
    if reason is None:
        return EXIT_REFUSED
    args = {"entry": a.entry, "pgn": a.pgn, "direction": a.direction if a.pgn is not None else None,
            "warning_shown": bool(warnings)}  # fmt: skip
    reply, code = c.call("remove", args, reason)
    if not reply.get("ok"):
        return c.refused(reply, code)
    c.say(f"Removed. New inventory {reply['result']['inventory']}.")
    return EXIT_OK


def cmd_clear(c: Ctl, a: argparse.Namespace) -> int:
    reason = c.confirm([f"mark {', '.join(a.events)} as reviewed"], [], a.reason)
    if reason is None:
        return EXIT_REFUSED
    reply, code = c.call("clear", {"events": a.events, "disposition": a.disposition}, reason)
    if not reply.get("ok"):
        return c.refused(reply, code)
    c.say(f"Cleared {len(reply['result']['cleared'])}. Light is now {reply['result']['light']}.")
    return EXIT_OK


def cmd_train(c: Ctl, a: argparse.Namespace) -> int:
    if a.action == "start":
        reason = c.confirm(["start training: record every device on this truck",
                            "detection runs as untrained until a new inventory is applied"], [],
                           a.reason or "training")  # fmt: skip
        if reason is None:
            return EXIT_REFUSED
        reply, code = c.call("train_start", {}, reason)
        if not reply.get("ok"):
            return c.refused(reply, code)
        c.say(
            f"Training started. It stops by itself after {reply['result']['timeout_min']} minutes."
        )
        c.say("Next step: drive through key-on engine off, idle and driving, then run train finish")
        return EXIT_OK
    if a.action == "status":
        reply, code = c.call("train_status")
        if not reply.get("ok"):
            return c.refused(reply, code)
        r = reply["result"]
        cov = r["coverage"]
        c.say(f"Training for {r['elapsed_s'] // 60} min, {r['remaining_s'] // 60} min left"
              f"{' (timed out)' if r['timed_out'] else ''}")  # fmt: skip
        c.say(f"Conditions covered: {', '.join(cov['conditions']) or 'none yet'}")
        c.say(f"Still to cover: {', '.join(cov['missing']) or 'none'}")
        c.say(f"Devices found: {len(cov['pgns_per_ecu'])}")
        for ecu in cov["pgns_per_ecu"]:
            count = len({p for pgns in ecu["pgns"].values() for p in pgns})
            c.say(f"  {ecu['name'] or 'no NAME'} at SA {ecu['addresses']}: {count} PGNs")
        return EXIT_OK
    reply, code = c.call("train_finish", {"pto_declared": a.pto})
    if not reply.get("ok"):
        return c.refused(reply, code)
    proposal = reply["result"]
    c.say(f"Proposed inventory {proposal['inventory']}:")
    for e in proposal["entries"]:
        c.say(f"  {e['entry']}  {e.get('name') or 'no NAME'}  SA {e.get('addresses')}  "
              f"{report.plain(e.get('category'))}  make {e.get('make')}  "
              f"{len(e.get('pgns_sent', []))} PGNs sent")  # fmt: skip
    apply = c.yes or c.ask("Apply this inventory? y/N ").strip().lower() in ("y", "yes")
    reason = a.reason or ("training confirmed" if apply else "training rejected")
    reply, code = c.call("train_confirm", {"apply": apply}, reason)
    if not reply.get("ok"):
        return c.refused(reply, code)
    c.say(f"Applied as {reply['result']['inventory']} from the next session." if apply
          else "Not applied; the old inventory stays.")  # fmt: skip
    return EXIT_OK


def cmd_config(c: Ctl, a: argparse.Namespace) -> int:
    if a.action == "show":
        reply, code = c.call("config_show")
        if not reply.get("ok"):
            return c.refused(reply, code)
        c.say(json.dumps(reply["result"]["config"], indent=2))
        return EXIT_OK
    new = json.loads(Path(a.file).read_text("utf-8"))
    current, code = c.call("config_show")
    old_doc = (current.get("result") or {}).get("config") if current.get("ok") else None
    old = validate(old_doc) if old_doc is not None else None
    checked = validate(new, old if isinstance(old, Config) else None)  # STS-17: on the laptop first
    if isinstance(checked, ConfigError):
        c.say("This config is not valid; nothing was sent:")
        for r in checked.reasons:
            c.say(f"  - {r}")
        return EXIT_REFUSED
    warnings = [f"weakens detection: {w}" for w in checked.weakens]
    if checked.weakens and not a.confirm:
        return c.refused({"error": "this change weakens detection", "next": "add --confirm"})
    changes = [f"save config {checked.version}, used from the next session"]
    changes += [f"change {k}" for k in checked.changed]
    reason = c.confirm(changes, warnings, a.reason)
    if reason is None:
        return EXIT_REFUSED
    reply, code = c.call("config_push", {"config": new, "confirm": a.confirm}, reason)
    if not reply.get("ok"):
        return c.refused(reply, code)
    c.say(f"Saved {reply['result']['config']}; it applies from the next session.")
    return EXIT_OK


def cmd_inventory(c: Ctl, a: argparse.Namespace) -> int:
    if a.offline:
        doc = report.newest_inventory(Path(a.offline))  # LAP-12: no logger needed
        if doc is None:
            return c.refused(
                {"error": f"no inventory in {a.offline}", "next": "run retrieve first"}
            )
    else:
        reply, code = c.call("inventory_show")
        if not reply.get("ok"):
            return c.refused(reply, code)
        doc = reply["result"]["inventory"]
        if doc is None:
            return c.refused({"error": "the logger is untrained", "next": "run train start"})
    if a.action == "export":
        target = Path(a.out or f"{doc.get('inventory')}.csv")
        target.write_text(report.inventory_csv(doc), encoding="utf-8")  # LAP-13
        c.say(f"Wrote {target}")
        return EXIT_OK
    c.say(f"Inventory {doc.get('inventory')} for VIN {doc.get('vin')}:")
    for e in doc.get("entries", []):
        c.say(f"  {e['entry']}  {e.get('name') or 'no NAME'}  SA {e.get('addresses')}  "
              f"{report.plain(e.get('category'))}  make {e.get('make')}")  # fmt: skip
    return EXIT_OK


def cmd_retrieve(c: Ctl, a: argparse.Namespace) -> int:
    assert c.t is not None
    result, reply = retrieve(c.t, Path(a.folder))
    if result is None:
        return c.refused(reply, NOT_RUNNING if "not running" in str(reply.get("error")) else 1)
    c.say(
        f"Copied {len(result.copied)} file(s), {len(result.skipped)} already here, "
        f"into {result.folder}"
    )
    for remote, kept in result.renamed:
        c.say(f"  {remote} changed on the logger; kept the new copy as {kept}")
    state = "verified" if result.chain_ok else "BROKEN"
    c.say(f"Chain check: {state}{' (open session in progress)' if result.in_progress else ''}")
    for p in result.problems:
        c.say(f"  {p}")
    c.say(f"Latest chain hash: {result.last_hash}")
    c.say("Next step: run report")
    return EXIT_OK if result.chain_ok else EXIT_REFUSED


def cmd_report(c: Ctl, a: argparse.Namespace) -> int:
    folder = Path(a.report_folder)
    if not (folder / "sessions").is_dir():
        return c.refused({"error": f"no retrieved logs in {folder}",
                          "next": "run retrieve, then report --folder logs/<VIN>"})  # fmt: skip
    text = report.build(folder)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (folder.parent / f"report-{folder.name}-{stamp}.txt").write_text(text, encoding="utf-8")
    (folder.parent / f"events-{folder.name}.csv").write_text(report.events_csv(report.load(folder)),
                                                              encoding="utf-8")  # fmt: skip
    c.out.write(text)
    return EXIT_OK


def cmd_restart(c: Ctl, a: argparse.Namespace) -> int:
    reason = c.confirm(["restart the logger software; recording resumes in a few seconds"], [],
                       a.reason)  # fmt: skip
    if reason is None:
        return EXIT_REFUSED
    reply, code = c.call("restart", {}, reason)
    if not reply.get("ok"):
        return c.refused(reply, code)
    c.say("Restarting.")
    return EXIT_OK


def cmd_retrain(c: Ctl, a: argparse.Namespace) -> int:
    reason = c.confirm(["archive the current inventory (nothing is deleted)",
                        "run untrained from the next session until a training is applied"],
                       ["every device will show as new until you train again"],
                       a.reason)  # fmt: skip
    if reason is None:
        return EXIT_REFUSED
    reply, code = c.call("retrain", {}, reason)
    if not reply.get("ok"):
        return c.refused(reply, code)
    c.say(f"Archived {reply['result']['archived']}. Next step: run train start")
    return EXIT_OK


# -- parser --------------------------------------------------------------------------------

OFFLINE = {"report"}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="j1939ctl", description="Maintenance laptop tool for the "
                                 "J1939 connected-devices logger.")  # fmt: skip
    ap.add_argument("--version", action="version", version=f"j1939ctl {VERSION}")
    ap.add_argument("--host", default=DEFAULT_HOST, help="the logger's address (SSH host)")
    ap.add_argument("--card", default=DEFAULT_CARD, help="the card's path on the logger")
    ap.add_argument("--folder", default="logs", help="where retrieved logs are kept")
    ap.add_argument("--yes", action="store_true", help="do not ask y/N")
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")

    def add(name: str, help_text: str, reason: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        if reason:
            p.add_argument("--reason", help="why (asked at the prompt if not given)")
        return p

    add("status", "home screen: state, VIN, events, training, card, clock, next step")
    t = add("train", "start, show or finish training", reason=True)
    t.add_argument("action", choices=["start", "status", "finish"])
    t.add_argument("--pto", action="store_true", help="declare PTO used during training")
    e = add("events", "list events to review by event ID")
    e.add_argument("--all", action="store_true", help="include reviewed events")
    p = add("approve", "approve a logged device, new PGN or address change", reason=True)
    p.add_argument("event", help="event ID, for example 142-37")
    r = add("remove", "remove a device, or one PGN, from the inventory", reason=True)
    r.add_argument("entry", help="entry ID, for example E07")
    r.add_argument("--pgn", type=int)
    r.add_argument("--direction", choices=["sent", "requested"], default="sent")
    c = add("clear", "mark high events as reviewed", reason=True)
    c.add_argument("events", nargs="+", help="event IDs")
    c.add_argument("--disposition", help="what it was, for example 'shop scan tool'")
    g = add("config", "show the config, or push a new version", reason=True)
    g.add_argument("action", choices=["show", "push"])
    g.add_argument("file", nargs="?")
    g.add_argument("--confirm", action="store_true", help="accept a change that weakens detection")
    i = add("inventory", "show the inventory, or export it as CSV")
    i.add_argument("action", choices=["show", "export"])
    i.add_argument("--from-folder", dest="offline", help="a retrieved folder (works offline)")
    i.add_argument("--out", help="CSV file to write")
    add("retrieve", "copy new logs into the VIN folder and check the chain")
    rp = add("report", "write the review report and events.csv (works offline)")
    rp.add_argument("report_folder", help="a retrieved folder, for example logs/<VIN>")
    add("restart", "restart the logger software", reason=True)
    add("retrain", "archive the inventory and return to untrained mode", reason=True)
    return ap


COMMANDS: dict[str, Callable[[Ctl, argparse.Namespace], int]] = {
    "status": cmd_status, "train": cmd_train, "events": cmd_events, "approve": cmd_approve,
    "remove": cmd_remove, "clear": cmd_clear, "config": cmd_config, "inventory": cmd_inventory,
    "retrieve": cmd_retrieve, "report": cmd_report, "restart": cmd_restart, "retrain": cmd_retrain,
}  # fmt: skip


def main(
    argv: Optional[Sequence[str]] = None,
    transport: Optional[Transport] = None,
    out: Optional[TextIO] = None,
    ask: Optional[Ask] = None,
) -> int:
    out = out or sys.stdout
    try:
        a = parser().parse_args(argv)
    except SystemExit as exc:  # --help or a usage error
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    if a.command == "config" and a.action == "push" and not a.file:
        out.write(
            "Refused: config push needs a file\nNext step: j1939ctl config push cfg-v4.json\n"
        )
        return EXIT_USAGE
    offline = a.command in OFFLINE or (a.command == "inventory" and a.offline)
    t = None if offline else (transport or SshTransport(a.host, a.card))
    ctl = Ctl(t, out, ask or input, a.yes)
    if t is not None:
        reply, code = t.call("login", {"tool_version": VERSION, "connection": "ssh"})
        if not reply.get("ok") and code == NOT_RUNNING and a.command not in ("status", "retrieve"):
            return ctl.refused(reply, code)
    try:
        return COMMANDS[a.command](ctl, a)
    finally:
        if t is not None:
            t.call("logout", {"tool_version": VERSION, "connection": "ssh"})
