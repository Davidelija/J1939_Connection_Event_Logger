"""retention: keep the card from filling (docs/modules.md section 4, v1, frozen for step 6).

Layer 3: decides, and ``store.free()`` deletes. Built to DC-20 (LOG-11, LOG-22).

``Retention(settings).check(usage, raw_files)`` runs at session start and after
each raw capture. When free space is below ``storage.event_reserve_mb`` plus
``limits.raw_mb_per_session``, it lists raw captures to free: retrieved ones
first, then unretrieved ones, oldest first in each, until free space is back
above that level. Only raw captures are ever listed: never session files
(CLAUDE.md rule 9) and never diagnostic files, which rotate themselves. It
returns a notice ``fault`` at ``storage.warn_pct`` card use (once per session)
and a high ``fault`` "card full; raw captures stopped" when only the reserve is
left (once per session); ``raw_allowed`` is then False.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from j1939logger.store import CardUsage
from j1939logger.types import Record

__all__ = ["Retention", "RawFile", "Plan"]

MB = 1024 * 1024


@dataclass(frozen=True)
class RawFile:
    path: Path
    mtime: float
    size: int
    retrieved: bool = False


@dataclass(frozen=True)
class Plan:
    free: list[Path] = field(default_factory=list)
    faults: list[Record] = field(default_factory=list)
    raw_allowed: bool = True
    free_bytes_after: int = 0


class Retention:
    def __init__(self, settings: Mapping[str, Any]) -> None:
        self._reserve = int(float(settings["storage.event_reserve_mb"]) * MB)
        self._raw_budget = int(float(settings["limits.raw_mb_per_session"]) * MB)
        self._warn_pct = float(settings["storage.warn_pct"])
        self._warned = False
        self._full = False

    def check(self, usage: CardUsage, raw_files: Iterable[RawFile]) -> Plan:
        target = self._reserve + self._raw_budget
        free = usage.free_bytes
        chosen: list[Path] = []
        if free < target:
            order = sorted(raw_files, key=lambda r: (not r.retrieved, r.mtime, str(r.path)))
            for r in order:  # retrieved first, then unretrieved, oldest first (LOG-11)
                if free >= target:
                    break
                chosen.append(r.path)
                free += r.size
        used = max(0, usage.used_bytes - (free - usage.free_bytes))
        pct = round(100.0 * used / usage.total_bytes, 1) if usage.total_bytes else 0.0
        faults: list[Record] = []
        if pct >= self._warn_pct and not self._warned:
            self._warned = True
            faults.append(
                Record(
                    "fault",
                    "notice",
                    None,
                    None,
                    {
                        "cause": f"card nearly full ({pct}% used)",
                        "logger_action": "freeing raw captures in the agreed order",
                    },
                )
            )
        raw_allowed = free > self._reserve
        if not raw_allowed and not self._full:
            self._full = True
            faults.append(
                Record(
                    "fault",
                    "high",
                    None,
                    None,
                    {
                        "cause": "card full; raw captures stopped",
                        "logger_action": "event records continue in the reserve",
                    },
                )
            )
        return Plan(chosen, faults, raw_allowed, free)
