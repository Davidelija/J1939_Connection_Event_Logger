"""The platform functions (docs/modules.md section 4, platform contract v2, DC-5).

Every hardware implementation (desktop ``vcan0``, DG Beacon, a backup board)
provides these nine functions; everything else in the logger reaches the
hardware only through them (CLAUDE.md rule 12, docs/porting.md section 3).
Implementations raise only ``PlatformError`` with a ``kind`` from
``FAULT_KINDS``; a bad argument (an unknown light pattern or operation) is a
programming error and raises ``ValueError`` (DC-6).
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from j1939logger.types import ClockReading

__all__ = ["Platform", "Paths", "LIGHT_PATTERNS", "FAULT_KINDS", "FAULT_OPS"]

# set_light() patterns (STS-1): steady, slow blink, fast blink, off.
LIGHT_PATTERNS = ("steady", "slow", "fast", "off")

# fault(op) operations (DC-5). Layer 1 modules call platform.fault(op) just
# before each such operation:
#   can_recv     capture, before each recvmsg on the CAN socket
#   can_send     transmit, before each send on the CAN socket
#   card_write   eventlog, store and rawcap, before each write to the card
#   card_sync    eventlog and store, before each fsync of a card file or directory
#   flash_write  store, before each write of state.json to internal flash
FAULT_OPS = ("can_recv", "can_send", "card_write", "card_sync", "flash_write")

# The Kind column of docs/errors.md, in table order. That column is the single
# list of fault kinds; tests/contract checks that this tuple matches it exactly.
FAULT_KINDS = (
    "can_missing",
    "can_down",
    "no_bitrate",
    "bus_off",
    "error_passive",
    "enobufs",
    "tx_breach",
    "rx_overflow",
    "bad_frame",
    "tp_error",
    "etp",
    "claim_change",
    "cannot_claim",
    "same_name_two_sa",
    "enospc",
    "erofs",
    "eio",
    "card_removed",
    "slow_sync",
    "card_nearly_full",
    "truncated_line",
    "temp_files",
    "corrupt_file",
    "card_not_ext4",
    "state_missing",
    "state_corrupt",
    "state_unwritable",
    "rtc_invalid",
    "vehicle_time_late",
    "vehicle_time_off",
    "clock_jump",
    "exception",
    "hang",
    "restart_loop",
    "cmd_not_running",
    "cmd_busy",
    "cmd_invalid_id",
    "cmd_wrong_state",
    "cmd_bad_proto",
    "ssh_host_key",
    "ssh_passphrase",
    "ssh_timeout",
    "link_dropped",
    "long_path",
    "folder_readonly",
    "name_collision",
    "cannot_connect",
)


@dataclass(frozen=True)
class Paths:
    """Storage locations returned by ``paths()``."""

    card: Path  # removable ext4 card: sessions, raw captures, supporting files
    flash: Path  # internal flash: state.json (LOG-5); never the card
    keys: Path  # operator keys and the fingerprint-to-name file (LAP-8); never the card


@runtime_checkable
class Platform(Protocol):
    """The hardware boundary (layer 0)."""

    def open_can(self, listen_only: bool) -> socket.socket:
        """Open a raw CAN socket (AF_CAN, CAN_RAW) in listen-only or normal mode."""
        ...

    def bitrate_check(self) -> Optional[int]:
        """Confirm 250000 or 500000 bit/s from clean received frames; None if not confirmed."""
        ...

    def set_light(self, pattern: str) -> None:
        """Show one of LIGHT_PATTERNS on the one status indicator."""
        ...

    def now(self) -> ClockReading:
        """Wall-clock time with its source and validity, and monotonic time for timers."""
        ...

    def rtc_ok(self) -> bool:
        """Whether the real-time clock is valid."""
        ...

    def on_wake(self) -> tuple[float, float]:
        """(wake_mono, ready_mono) for the session header (HW-8)."""
        ...

    def watchdog_kick(self) -> None:
        """Notify the watchdog that the logger is alive (STS-18)."""
        ...

    def paths(self) -> Paths:
        """Card, internal flash and key locations."""
        ...

    def fault(self, op: str) -> None:
        """Called just before an operation in FAULT_OPS (DC-5).

        Raises ``PlatformError`` when an injected fault is due for ``op``, or
        delays the call for ``slow_sync`` (the desktop fault plan); hardware
        implementations do nothing.
        """
        ...
