"""The laptop command handlers and the operator calls (STS-23, DC-20, DC-21).

Part of ``Session`` (docs/modules.md section 4); split from session.py with no change
in behaviour.
"""

from __future__ import annotations

import json
import queue
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

from j1939logger.admin import RESTART_EXIT, reset_record
from j1939logger.config import (
    Config,
    ConfigError,
    change_record,
    rejected_record,
    validate,
)
from j1939logger.eventlog import format_utc
from j1939logger.inventory import (
    InventoryRefused,
    Training,
    approve,
    confirm_record,
    next_version,
    rejection_record,
    remove,
)
from j1939logger.session.files import (
    _refused,
    _version_number,
    card_files,
    session_files,
)
from j1939logger.session.state import _State
from j1939logger.types import J1939Msg, Record


class _CommandsPart(_State):
    CHANGING = frozenset(
        {
            "login",
            "logout",
            "train_start",
            "train_finish",
            "train_confirm",
            "approve",
            "remove",
            "clear",
            "config_push",
            "retrieved",
            "restart",
            "retrain",
        }
    )

    def handle(
        self,
        cmd: str,
        args: Optional[Mapping[str, Any]] = None,
        operator: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run one laptop command in the main loop; the protocol reply (``proto`` 1)."""
        args = dict(args or {})
        if cmd in self.CHANGING and not operator:
            return _refused("unknown operator key", "install the key with release/keys.sh")
        if self.eventlog is None and cmd not in ("status", "events", "inventory_show",
                                                 "config_show", "retrieve_list"):  # fmt: skip
            return _refused("no session is open", "wait for CAN activity, then retry")
        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler is None:
            return _refused(f"unknown command {cmd!r}", "run j1939ctl --help")
        try:
            result = handler(args, operator, reason)
        except InventoryRefused as exc:
            return _refused(str(exc), "check the ID with events or inventory show")
        except (ValueError, KeyError, TypeError) as exc:
            return _refused(f"bad arguments: {exc}", f"run j1939ctl {cmd} --help")
        self._update_status(force=True)
        return {"proto": 1, "ok": True, "result": result}

    def _run_commands(self) -> None:
        """Answer the commands cmdserver queued, in order (STS-23 (c))."""
        while True:
            try:
                pending = self.commands.get_nowait()
            except queue.Empty:
                return
            req = pending.request
            try:
                pending.reply = self.handle(
                    str(req.get("cmd")), req.get("args"), req.get("operator"), req.get("reason")
                )
            except Exception as exc:  # a command never stops the logger (rule 14)
                self.diag.log("error", "cmdserver", f"{type(exc).__name__}: {exc}")
                pending.reply = _refused("internal error", "check the diagnostic log")
            pending.done.set()

    def _need_reason(self, reason: Optional[str]) -> str:
        if not reason:
            raise InventoryRefused("a reason is required")
        return reason

    def _cmd_status(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        from j1939logger.status import contents

        body = contents(self.status_state(), self._now_text())
        body["vin"] = self._vin_received or self._inventory_vin
        body["unreviewed"] = list(self._unreviewed)
        return body

    def _cmd_login(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        fields = {"operator": operator, "connection": args.get("connection", "ssh"),
                  "tool_version": args.get("tool_version")}  # fmt: skip
        self._log(Record("operator_login", "notice", None, None, fields))
        return {"operator": operator}

    def _cmd_logout(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        fields = {"operator": operator, "connection": args.get("connection", "ssh"),
                  "tool_version": args.get("tool_version")}  # fmt: skip
        self._log(Record("operator_logout", "info", None, None, fields))
        return {"operator": operator}

    def _cmd_train_start(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        if self.training is not None:
            raise InventoryRefused("training is already running")
        self.train_start(str(operator))
        return {"timeout_min": self._settings["training.timeout_min"]}

    def _cmd_train_status(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        t = self.training
        if t is None:
            raise InventoryRefused("training is not running")
        elapsed = self.clock.mono() - t.start_mono
        total = float(self._settings["training.timeout_min"]) * 60.0
        return {"elapsed_s": round(elapsed), "remaining_s": max(0, round(total - elapsed)),
                "timed_out": t.timed_out, "coverage": t.coverage()}  # fmt: skip

    def _cmd_train_finish(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return self.train_finish(str(operator), bool(args.get("pto_declared", False)))

    def _cmd_train_confirm(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        version = self.confirm_inventory(str(operator), bool(args["apply"]), reason)
        if version is not None:
            self._inventory_active = True  # a confirmed training ends a retrain
            self._save_state()
        return {"inventory": version}

    def _event_rows(self, include_all: bool) -> list[dict[str, Any]]:
        rows = []
        wanted = set(self._unreviewed)
        for f in session_files(self._sessions_dir):
            for line in f.path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                eid = f"{f.session}-{r.get('rec')}"
                if r.get("type") in ("session_start", "session_end"):
                    continue
                if include_all or eid in wanted:
                    rows.append({"event": eid, "type": r.get("type"), "sev": r.get("sev"),
                                 "utc": r.get("utc"), "sa": r.get("sa"), "name": r.get("name"),
                                 "category": r.get("category"), "pgn": r.get("pgn"),
                                 "entry": r.get("entry"), "direction": r.get("direction"),
                                 "reviewed": eid not in wanted})  # fmt: skip
        return rows

    def _cmd_events(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"events": self._event_rows(bool(args.get("all", False)))}

    def _cmd_approve(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        event = str(args["event"])
        version = self.approve(event, str(operator), self._need_reason(reason),
                               bool(args.get("warning_shown", False)))  # fmt: skip
        if event in self._unreviewed:  # the approval clears its event (LAP-11)
            self._unreviewed.remove(event)
            self._save_state()
        return {"inventory": version, "cleared": [event]}

    def _cmd_remove(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        pgn = args.get("pgn")
        version = self.remove(str(args["entry"]), str(operator), self._need_reason(reason),
                              int(pgn) if pgn is not None else None, args.get("direction"),
                              bool(args.get("warning_shown", False)))  # fmt: skip
        return {"inventory": version}

    def _cmd_clear(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        events = [str(e) for e in args["events"]]
        why = self._need_reason(reason)
        not_open = [e for e in events if e not in self._unreviewed]
        if not events or not_open:
            raise InventoryRefused(
                f"not unreviewed high events: {', '.join(not_open) or 'none given'}"
            )
        for e in events:
            self._unreviewed.remove(e)
        self._save_state()
        from j1939logger.status import light

        after = light(self.status_state())
        self._log(Record("review_clear", "notice", None, None, {
            "operator": operator, "cleared": events, "disposition": args.get("disposition"),
            "reason": why, "approve_device": False, "light": after,
        }))  # fmt: skip
        return {"cleared": events, "light": after}

    def _cmd_config_show(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"config": self._newest("config")}

    def _cmd_config_push(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        new_doc = args["config"]
        old_doc = self._newest("config")
        old = validate(old_doc) if old_doc is not None else None
        if not isinstance(old, Config):
            raise InventoryRefused("the active config is not on the card")
        checked = validate(new_doc, old)
        proposed = new_doc.get("config") if isinstance(new_doc, Mapping) else None
        if isinstance(checked, ConfigError):
            self._log(rejected_record(checked, proposed, str(operator), None))
            raise InventoryRefused(f"config rejected: {checked}")
        if checked.version in [f"cfg-v{v}" for v in self.store.versions("config")]:
            raise InventoryRefused(f"{checked.version} already exists; raise the version")
        if checked.weakens and not args.get("confirm"):
            raise InventoryRefused(
                f"weakens detection ({', '.join(checked.weakens)}): add --confirm"
            )
        data = (json.dumps(new_doc, indent=2) + "\n").encode("utf-8")
        if not self.store.write_atomic("config", checked.version, data):
            raise InventoryRefused("the new config could not be saved")
        self._log(change_record(checked, old, str(operator), None))
        return {"config": checked.version, "changed": list(checked.changed),
                "weakens": list(checked.weakens)}  # fmt: skip

    def _cmd_inventory_show(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"inventory": self._inventory_doc()}

    def _cmd_retrieve_list(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        return {"files": card_files(self._platform.paths().card)}

    def _cmd_retrieved(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        files = [str(f) for f in args.get("files", [])]
        for f in files:
            if f not in self._retrieved:
                self._retrieved.append(f)
        self._save_state()
        sessions = sorted({int(Path(f).name[1:7]) for f in files
                           if f.startswith("sessions/")
                           and Path(f).name[1:7].isdigit()})  # fmt: skip
        raw = [f for f in files if f.startswith("raw/")]
        partial = [self._session] if self._session in sessions else []
        self._log(Record("retrieval", "info", None, None, {
            "operator": operator, "sessions": sessions, "partial": partial, "raw_files": len(raw),
            "chain_verified": bool(args.get("chain")), "last_hash": args.get("last_hash"),
        }))  # fmt: skip
        return {"retrieved": len(files)}

    def _cmd_restart(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        self._log(reset_record("restart", str(operator), self._need_reason(reason)))
        self._unclean_starts = []  # an operator restart clears the restart guard (NP-19)
        self._save_state()
        self.exit_code = RESTART_EXIT
        self.stop()
        return {"exit_code": RESTART_EXIT}

    def _cmd_retrain(
        self, args: dict[str, Any], operator: Optional[str], reason: Optional[str]
    ) -> Any:
        archived = self._versions.get("inventory")
        self._log(reset_record("retrain", str(operator), self._need_reason(reason), archived))
        self._inventory_active = False  # untrained from the next session (STS-12)
        self._save_state()
        return {"archived": archived}

    def _now_text(self) -> Optional[str]:
        return format_utc(self.clock.to_utc(self.clock.mono()))

    def _stored_inventories(self) -> list[dict[str, Any]]:
        out = []
        for v in self.store.versions("inventory"):
            data = self.store.load("inventory", v)
            try:
                doc = json.loads(data.decode("utf-8")) if data is not None else None
            except (ValueError, UnicodeDecodeError):
                doc = None
            if isinstance(doc, dict):
                out.append(doc)
        return out

    def _inventory_doc(self) -> Optional[dict[str, Any]]:
        """The inventory that operator changes build on: the newest saved version, so changes
        made in one session chain (each still applies from the next session), else the active
        inventory as an ``inv-1`` dict."""
        if self._inventory is None:
            return None
        active = _version_number(self._inventory.version)
        newest = None
        for doc in self._stored_inventories():
            n = _version_number(str(doc.get("inventory")))
            if n is not None and (newest is None or n > newest[0]):
                newest = (n, doc)
        if newest is not None and (active is None or newest[0] >= active):
            return newest[1]
        return {
            "format": "inv-1",
            "inventory": self._inventory.version,
            "vin": self._inventory.vin,
            "entries": [dict(e.raw) for e in self._inventory.entries],
        }

    def _next_inventory_version(self) -> str:
        numbers = set(self.store.versions("inventory"))
        if self._inventory is not None:
            m = re.match(r"^inv-v(\d+)$", self._inventory.version)
            if m:
                numbers.add(int(m.group(1)))
        if self._proposal is not None:
            m = re.match(r"^inv-v(\d+)$", str(self._proposal.get("inventory")))
            if m:
                numbers.add(int(m.group(1)))
        return next_version(numbers)

    def _write_inventory(self, doc: dict[str, Any]) -> bool:
        """Save a new version through store; it applies from the next session (DC-20)."""
        data = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        return self.store.write_atomic("inventory", str(doc["inventory"]), data)

    def train_start(self, operator: str) -> None:
        """Start training (TRN-2): observe every device; this session runs untrained."""
        if self.eventlog is None or self.detect is None:
            raise InventoryRefused("no session is open")
        now = self.clock.mono()
        self.training = Training(self._settings, now, self._logger_name, operator)
        for sa in range(254):  # NAMEs already claimed this session
            name = self.detect.name_at(sa)
            if name is not None:
                data = name.to_bytes(8, "little")
                self.training.observe(
                    J1939Msg(now, 0.0, 6, 60928, sa, 255, data, False, False, False)
                )
        self._proposal = None
        self._drop_inventory()  # detection runs as in untrained mode during training
        self._log(
            Record(
                "training_start",
                "notice",
                None,
                None,
                {"operator": operator, "states": list(self._settings["training.states"])},
            )
        )

    def train_finish(self, operator: str, pto_declared: bool = False) -> dict[str, Any]:
        """Stop training and return the proposed inventory; not applied until confirmed (TRN-4)."""
        if self.training is None:
            raise InventoryRefused("training is not running")
        t = self.training
        t.observing(self.clock.mono())
        timed_out = t.timed_out
        t.stopped = True
        lib = self.library.manufacturers if self.library is not None else None
        proposal = t.propose(
            previous=self._inventory_doc(),
            stored=self._stored_inventories(),
            version=self._next_inventory_version(),
            vin=self._vin_received,
            session=self._session,
            now_utc=self._now_text(),
            manufacturers=lib,
            pto_declared=pto_declared,
        )
        coverage = t.coverage(pto_declared)
        self._log(
            Record(
                "training_finish",
                "notice",
                None,
                None,
                {
                    "operator": operator,
                    "states_covered": coverage["conditions"],
                    "inventory_proposed": proposal["inventory"],
                    "coverage": coverage,
                    "timed_out": timed_out,
                },
            )
        )
        self.training = None
        self._proposal = proposal
        return proposal

    def confirm_inventory(
        self, operator: str, apply: bool, reason: Optional[str] = None
    ) -> Optional[str]:
        """Apply (save) or reject the proposed inventory; the new version, or None (TRN-4)."""
        if self._proposal is None:
            raise InventoryRefused("no proposed inventory")
        proposal, self._proposal = self._proposal, None
        if not apply:
            self._log(rejection_record(proposal, operator, reason))
            return None
        if not self._write_inventory(proposal):
            raise InventoryRefused("the new inventory could not be saved")
        self._log(confirm_record(proposal, operator, reason))
        return str(proposal["inventory"])

    def _find_event(self, event_id: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
        """The logged record for ``session-rec``, and its connection_end if it has one."""
        m = re.match(r"^(\d+)-(\d+)$", event_id)
        if m is None:
            raise InventoryRefused(f"bad event ID {event_id}")
        session, rec = int(m.group(1)), int(m.group(2))
        records: list[dict[str, Any]] = []
        for f in session_files(self._sessions_dir):
            if f.session != session:
                continue
            for line in f.path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue  # an incomplete last line
        event = next((r for r in records if r.get("rec") == rec), None)
        if event is None:
            raise InventoryRefused(f"event {event_id} not found")
        end = None
        if event.get("type") == "connection_start":
            end = next(
                (
                    r
                    for r in records
                    if r.get("type") == "connection_end" and r.get("conn") == event.get("conn")
                ),
                None,
            )
        return event, end

    def approve(
        self, event_id: str, operator: str, reason: str, warning_shown: bool = False
    ) -> str:
        """Approve a logged device, new PGN or address change (TRN-5, TRN-10); the new version."""
        doc = self._inventory_doc()
        if doc is None:
            raise InventoryRefused("no inventory to approve into (untrained)")
        event, end = self._find_event(event_id)
        version = self._next_inventory_version()
        new, record = approve(
            doc,
            event,
            event_id=event_id,
            end=end,
            stored=self._stored_inventories(),
            version=version,
            operator=operator,
            reason=reason,
            session=self._session,
            now_utc=self._now_text(),
            warning_shown=warning_shown,
            control_pgns=self._settings["detection.control_pgns"],
        )
        if not self._write_inventory(new):
            raise InventoryRefused("the new inventory could not be saved")
        self._log(record)
        return version

    def remove(
        self,
        entry_id: str,
        operator: str,
        reason: str,
        pgn: Optional[int] = None,
        direction: Optional[str] = None,
        warning_shown: bool = False,
    ) -> str:
        """Remove an entry or one of its PGNs (TRN-14, TRN-15); the new version."""
        doc = self._inventory_doc()
        if doc is None:
            raise InventoryRefused("no inventory to remove from (untrained)")
        version = self._next_inventory_version()
        new, record = remove(
            doc,
            entry_id,
            version=version,
            operator=operator,
            reason=reason,
            session=self._session,
            now_utc=self._now_text(),
            pgn=pgn,
            direction=direction,
            warning_shown=warning_shown,
        )
        if not self._write_inventory(new):
            raise InventoryRefused("the new inventory could not be saved")
        self._log(record)
        return version
