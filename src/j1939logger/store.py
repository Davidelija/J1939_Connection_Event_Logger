"""store: load and write every supporting file (docs/modules.md section 4, contract v1).

Layer 1; frozen for step 2. The only writer of supporting files (CLAUDE.md
rule 15): status, inventory and config versions, the device library (which
holds the manufacturer list, IDN-2; DC-10) and ``state.json``. It never writes
session files or raw captures.

Layout (docs/log-format.md):

* card: ``status.json``, ``inventory/inv-vN.json``, ``config/cfg-vN.json``,
  ``library/lib-vN.json``
* internal flash: ``state.json`` (never the card, LOG-5)

``write_atomic`` writes a temporary file, syncs it, renames it into place and
syncs the directory (LOG-23). Version files are never overwritten. Leftover
temporary files (``.*.tmp``) are ignored. A missing file loads as None.
Storage errors never raise: they become a high ``fault`` record waiting in
``take_faults()`` (LOG-22).
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from j1939logger.platform.interface import Paths, Platform
from j1939logger.types import PlatformError, Record

__all__ = ["Store", "CardUsage", "KINDS"]

_VERSIONED = {
    "inventory": ("inventory", "inv"),
    "config": ("config", "cfg"),
    "library": ("library", "lib"),
}
KINDS = ("status", "inventory", "config", "library", "state")


@dataclass(frozen=True)
class CardUsage:
    total_bytes: int
    used_bytes: int
    free_bytes: int

    @property
    def used_pct(self) -> float:
        return round(100.0 * self.used_bytes / self.total_bytes, 1) if self.total_bytes else 0.0


class Store:
    def __init__(self, platform: Platform) -> None:
        self._platform = platform
        self._paths: Paths = platform.paths()
        self._faults: list[Record] = []

    # -- paths ----------------------------------------------------------------

    def _dir(self, kind: str) -> Path:
        if kind == "state":
            return self._paths.flash
        if kind == "status":
            return self._paths.card
        if kind in _VERSIONED:
            return self._paths.card / _VERSIONED[kind][0]
        raise ValueError(f"unknown kind {kind!r}; kinds are {KINDS}")

    def path(self, kind: str, version: Optional[int] = None) -> Path:
        if kind == "state":
            return self._dir(kind) / "state.json"
        if kind == "status":
            return self._dir(kind) / "status.json"
        prefix = _VERSIONED[kind][1] if kind in _VERSIONED else ""
        if version is None:
            raise ValueError(f"{kind} needs a version")
        return self._dir(kind) / f"{prefix}-v{version}.json"

    def versions(self, kind: str) -> list[int]:
        if kind not in _VERSIONED:
            raise ValueError(f"{kind} is not versioned")
        prefix = _VERSIONED[kind][1]
        folder = self._dir(kind)
        if not folder.is_dir():
            return []
        pattern = re.compile(rf"^{prefix}-v(\d+)\.json$")
        found = (pattern.match(p.name) for p in folder.iterdir())
        return sorted(int(m.group(1)) for m in found if m)

    # -- reading --------------------------------------------------------------

    def load(self, kind: str, version: Optional[int] = None) -> Optional[bytes]:
        """The file's bytes; the newest version when ``version`` is None; None if missing."""
        if kind in _VERSIONED and version is None:
            have = self.versions(kind)
            if not have:
                return None
            version = have[-1]
        path = self.path(kind, version)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            self._fault(exc, f"reading {path.name}", "file not read")
            return None

    # -- writing --------------------------------------------------------------

    def write_atomic(self, kind: str, name: str, data: bytes) -> bool:
        """Write a supporting file atomically. ``name`` is the version (``inv-v3``) or the kind.

        Returns False (and queues a fault record) on a storage error. Writing a
        version file that already exists is refused with ValueError: versions are
        never overwritten (LOG-23).
        """
        if kind in _VERSIONED:
            prefix = _VERSIONED[kind][1]
            m = re.match(rf"^{prefix}-v(\d+)$", name)
            if not m:
                raise ValueError(f"{kind} name must look like {prefix}-vN: {name!r}")
            target = self.path(kind, int(m.group(1)))
            if target.exists():
                raise ValueError(f"{target.name} exists; version files are never overwritten")
        elif kind in ("status", "state"):
            target = self.path(kind)
        else:
            raise ValueError(f"unknown kind {kind!r}")
        op = "flash_write" if kind == "state" else "card_write"
        sync_op = "flash_write" if kind == "state" else "card_sync"
        tmp = target.with_name(f".{target.name}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._platform.fault(op)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                os.write(fd, data)
                self._platform.fault(sync_op)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, target)
            self._sync_dir(target.parent)
        except (PlatformError, OSError) as exc:
            self._fault(exc, f"writing {target.name}", "file not written")
            return False
        return True

    @staticmethod
    def _sync_dir(folder: Path) -> None:
        try:
            fd = os.open(folder, os.O_RDONLY)
        except OSError:
            return  # directories cannot be opened for sync on every OS (the logger runs on Linux)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    # -- card space -------------------------------------------------------------

    def usage(self) -> CardUsage:
        u = shutil.disk_usage(self._paths.card)
        return CardUsage(total_bytes=u.total, used_bytes=u.used, free_bytes=u.free)

    def free(self, files: Iterable[Path]) -> int:
        """Delete raw captures that ``retention`` listed; returns how many were removed.

        Only files under the card's ``raw/`` folder are ever removed; session files
        never are (CLAUDE.md rule 9).
        """
        raw = (self._paths.card / "raw").resolve()
        removed = 0
        for f in files:
            p = Path(f).resolve()
            if raw not in p.parents:
                raise ValueError(f"store frees only raw captures: {p}")
            try:
                p.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                self._fault(exc, f"freeing {p.name}", "file not removed")
        return removed

    # -- faults -----------------------------------------------------------------

    def take_faults(self) -> list[Record]:
        out, self._faults = self._faults, []
        return out

    def _fault(self, exc: BaseException, what: str, action: str) -> None:
        kind = exc.kind if isinstance(exc, PlatformError) else type(exc).__name__
        self._faults.append(
            Record(
                type="fault",
                sev="high",
                utc=None,
                veh_time=None,
                fields={"cause": f"storage error ({kind}) {what}", "logger_action": action},
            )
        )
