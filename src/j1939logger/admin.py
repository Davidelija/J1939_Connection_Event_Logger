"""admin: restart, retrain and the diagnostic log (v1, frozen for step 7).

Layer 4. ``reset_record(mode, ...)`` builds the ``reset`` record for
``restart`` and ``retrain`` (STS-11, STS-12, DC-21); ``session`` carries them out:
a restart ends the process with ``RESTART_EXIT`` (75) for systemd to restart it,
and a retrain sets ``inventory_active: false`` in ``state.json``. The
diagnostic-log writer (LOG-20) was built in step 2:

* One line per event: ``<utc> <level> <module> <message>`` (docs/modules.md
  section 1), with ``+<seconds>s`` since wake in place of the UTC time while no
  valid time exists. Levels: ``error``, ``warning``, ``info``, ``debug``.
* A repeated message is written once; when a different one follows, the
  repeat count is written ("last message repeated N times").
* No evidence data (NAMEs, VINs, frames) belongs here, only references such as
  ``conn`` or ``event_id``. The log is not hash-chained and is not evidence.
* Size-capped and rotated: ``diag/logger.log`` up to ``diag.max_bytes``, then
  ``logger.log.1`` ... ``logger.log.<diag.files - 1>``.
* Restart causes: ``restart_cause(cause)`` writes a line the next session
  reads with ``last_restart_cause()`` to tell how the previous session ended
  (LOG-18, STS-18, DC-10).
* Writing never raises: a failure is counted in ``write_errors`` and dropped,
  so diagnostic logging never crashes the logger (CLAUDE.md rule 14).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from j1939logger.clock import Clock
from j1939logger.platform.interface import Platform
from j1939logger.types import PlatformError, Record

__all__ = [
    "DiagLog",
    "LEVELS",
    "RESTART_CAUSES",
    "RESTART_EXIT",
    "RESET_MODES_BUILT",
    "reset_record",
]

LEVELS = ("error", "warning", "info", "debug")
RESTART_CAUSES = ("software restart", "watchdog restart")
_RESTART_TAG = "restart cause: "
RESTART_EXIT = 75  # restart: systemd restarts the service (DC-21)
RESET_MODES_BUILT = ("restart", "retrain")  # move and wipe are Deferred


def reset_record(mode: str, operator: str, reason: str, archived: Optional[str] = None) -> Record:
    """The ``reset`` record (notice) for ``restart`` or ``retrain`` (STS-11, STS-12)."""
    if mode not in RESET_MODES_BUILT:
        raise ValueError(f"reset mode must be one of {RESET_MODES_BUILT}: {mode!r}")
    if not reason:
        raise ValueError("a reason is required")
    return Record(
        "reset",
        "notice",
        None,
        None,
        {"operator": operator, "mode": mode, "reason": reason, "archived": archived},
    )


class DiagLog:
    def __init__(self, platform: Platform, clock: Clock, max_bytes: int, files: int) -> None:
        self._platform = platform
        self._clock = clock
        self._dir = platform.paths().card / "diag"
        self._path = self._dir / "logger.log"
        self._max_bytes = max_bytes
        self._files = files
        self._last: Optional[tuple[str, str, str]] = None
        self._repeats = 0
        self.write_errors = 0

    @property
    def path(self) -> Path:
        return self._path

    def log(self, level: str, module: str, message: str) -> None:
        if level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}: {level!r}")
        key = (level, module, message)
        if key == self._last:
            self._repeats += 1
            return
        if self._repeats and self._last is not None:
            self._write(
                self._last[0], self._last[1], f"last message repeated {self._repeats} times"
            )
        self._last, self._repeats = key, 0
        self._write(level, module, message)

    def flush(self) -> None:
        """Write any pending repeat count (at session end)."""
        if self._repeats and self._last is not None:
            self._write(
                self._last[0], self._last[1], f"last message repeated {self._repeats} times"
            )
            self._repeats = 0

    def restart_cause(self, cause: str) -> None:
        """Record why the logger is about to restart, for the next session header."""
        if cause not in RESTART_CAUSES:
            raise ValueError(f"cause must be one of {RESTART_CAUSES}: {cause!r}")
        self.flush()
        self._last = None
        self._write("error", "admin", _RESTART_TAG + cause)

    def last_restart_cause(self) -> Optional[str]:
        """The restart cause in the newest log line, or None if the last line is not one."""
        try:
            lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        if not lines:
            return None
        last = lines[-1]
        i = last.find(_RESTART_TAG)
        if i < 0:
            return None
        cause = last[i + len(_RESTART_TAG) :].strip()
        return cause if cause in RESTART_CAUSES else None

    # -- file handling ------------------------------------------------------------

    def _stamp(self) -> str:
        r = self._clock.now()
        if r.wall_utc is not None:
            t = r.wall_utc
            return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
        return f"+{self._clock.elapsed_s(r.mono):.3f}s"

    def _write(self, level: str, module: str, message: str) -> None:
        line = f"{self._stamp()} {level} {module} {message}\n".encode("utf-8", "replace")
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len(line))
            self._platform.fault("card_write")
            fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except (PlatformError, OSError):
            self.write_errors += 1

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return
        if size + incoming <= self._max_bytes:
            return
        if self._files <= 1:
            self._path.unlink()
            return
        oldest = self._dir / f"logger.log.{self._files - 1}"
        if oldest.exists():
            oldest.unlink()
        for n in range(self._files - 2, 0, -1):
            src = self._dir / f"logger.log.{n}"
            if src.exists():
                os.replace(src, self._dir / f"logger.log.{n + 1}")
        os.replace(self._path, self._dir / "logger.log.1")
