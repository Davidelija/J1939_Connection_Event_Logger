"""New versions from the card, the status file and light, raw captures, retention, VIN mismatch.

Part of ``Session`` (docs/modules.md section 4); split from session.py with no change
in behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from j1939logger.config import (
    Config,
    Inventory,
    validate,
    validate_inventory,
)
from j1939logger.retention import RawFile
from j1939logger.session.files import (
    APPROVED,
    _version_number,
    settings_from_config,
)
from j1939logger.session.state import _State
from j1939logger.status import State
from j1939logger.types import Record


class _CardPart(_State):
    def _set_inventory(self, inv: Optional[Inventory]) -> None:
        self._inventory = inv
        entries = inv.entries if inv is not None else ()
        self._inventory_addresses = tuple(a for e in entries for a in e.addresses)
        self._inventory_vin = inv.vin if inv is not None else None
        self._known_addresses = {
            a for e in entries if e.name is not None and e.category != APPROVED for a in e.addresses
        }
        self._versions["inventory"] = inv.version if inv is not None else None

    def _newest(self, kind: str) -> Optional[dict[str, Any]]:
        versions = self.store.versions(kind)
        if not versions:
            return None
        data = self.store.load(kind, versions[-1])
        try:
            doc = json.loads(data.decode("utf-8")) if data is not None else None
        except (ValueError, UnicodeDecodeError):
            return None
        return doc if isinstance(doc, dict) else None

    def _reload_from_card(self) -> None:
        """At session open: the newest saved inventory and config apply (or none after retrain)."""
        if not self._inventory_active:
            self._set_inventory(None)
        else:
            doc = self._newest("inventory")
            if doc is not None:
                inv = validate_inventory(doc)
                current = _version_number(self._inventory.version) if self._inventory else None
                new = _version_number(str(doc.get("inventory")))
                if isinstance(inv, Inventory) and (current is None or (new or 0) >= current):
                    self._set_inventory(inv)
        cfg_doc = self._newest("config")
        if cfg_doc is not None:
            cfg = validate(cfg_doc)
            if isinstance(cfg, Config) and cfg.version != self._versions.get("config"):
                self._settings = settings_from_config(cfg_doc)
                self._versions["config"] = cfg.version

    def _state_name(self) -> str:
        if self.eventlog is None or self._header_pending:
            return "starting"
        if self._bitrate is None:
            return "detecting bit rate"
        if self.training is not None:
            return "training"
        if self._untrained:
            return "needs training"
        if self._high_fault is not None:
            return "fault"
        return "recording"

    def status_state(self) -> State:
        try:
            usage = self.store.usage()
            pct: Optional[float] = usage.used_pct
        except OSError:
            pct = None
        reading = self.clock.now()
        transmit = "on"
        if self._transmit_off_reason() is not None:
            transmit = f"off: {self._transmit_off_reason()}"
        elif self._guard_holds:
            transmit = "off: restart loop"
        retrieved = sorted({Path(f).name.split("_", 1)[0] for f in self._retrieved
                            if f.startswith("sessions/")})  # fmt: skip
        warn = float(self._settings.get("storage.warn_pct", 90))
        return State(
            state=self._state_name(),
            session=self._session or None,
            bitrate=self._bitrate,
            logger_sa=self.logger_sa,
            unreviewed_high=len(self._unreviewed),
            fault=self._high_fault,
            card_used_pct=pct,
            card_nearly_full=pct is not None and pct >= warn,
            clock_valid=reading.valid,
            clock_source=reading.source,
            untrained=self._untrained,
            retrieved=retrieved,
            training_coverage=self.training.coverage() if self.training is not None else None,
            config=self._versions.get("config"),
            inventory=self._versions.get("inventory"),
            library=self._versions.get("library"),
            transmit=transmit,
            vin_status=self._vin_status,
            restart_loop=self._guard_holds,
        )

    def _update_status(self, force: bool = False) -> None:
        now = self.clock.mono()
        if not force and now - self._status_mono < 0.5:
            return
        self._status_mono = now
        before = self.status.pattern
        data = self.status.update(self.status_state(), now, self._now_text())
        if self.status.pattern != before:
            self.diag.log("info", "status", f"light {self.status.pattern}")  # STS-1
        if data is not None:
            self.store.write_atomic("status", "status", data)

    def _raw_start(self, conn: int, ts_mono: float) -> Optional[str]:
        """Start a raw capture for an event; the name for ``raw_capture`` or None (LOG-10)."""
        if self.rawcap is None:
            return None
        before = self.capture.window(ts_mono - self.rawcap.before_s, ts_mono)
        return self.rawcap.start(conn, ts_mono, before)

    def _raw_poll(self) -> None:
        if self.rawcap is None:
            return
        if self.rawcap.poll(self.clock.mono()):
            self._retention()  # after each raw capture (DC-20)

    def _raw_files(self) -> list[RawFile]:
        folder = self._platform.paths().card / "raw"
        out = []
        for p in sorted(folder.glob("*.log")) if folder.is_dir() else []:
            try:
                st = p.stat()
            except OSError:
                continue
            done = f"raw/{p.name}" in self._retrieved  # retrieved first (LOG-11)
            out.append(RawFile(p, st.st_mtime, st.st_size, retrieved=done))
        return out

    def _retention(self) -> None:
        """Free raw captures when the card runs low; faults; stop captures at the reserve."""
        if self.retention is None:
            return
        try:
            usage = self.store.usage()
        except OSError:
            return
        plan = self.retention.check(usage, self._raw_files())
        if plan.free:
            self.store.free(plan.free)
        for fault in plan.faults:
            self._log(fault)
        if not plan.raw_allowed and self.rawcap is not None:
            self.rawcap.stop("card full; only the event reserve is left")  # LOG-22

    def _vin_mismatch(self, check: Record) -> None:
        self._log(
            Record(
                "vin_mismatch",
                "high",  # not capped (log-format severity rules)
                None,
                None,
                {
                    "vin": check.fields["vin"],
                    "inventory_vin": check.fields["inventory_vin"],
                    "inventory": check.fields["inventory"],
                    "logger_action": "rest of the session runs untrained",
                },
            )
        )
        self._drop_inventory()

    def _drop_inventory(self) -> None:
        self._dropped = True
        if self.detect is not None:
            self.detect.drop_inventory()
        if self.monitor is not None:
            self.monitor.drop_inventory()
