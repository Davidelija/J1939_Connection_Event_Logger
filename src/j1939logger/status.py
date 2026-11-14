"""status: the status file and the light (docs/modules.md section 4, v1, frozen for step 7).

Layer 3, with the section 2 exception: it calls ``platform.set_light()``.
Built to DC-21 (STS-1 to STS-3).

* ``light(state)``: off while starting and detecting the bit rate; fast blink
  for a high fault, a VIN mismatch, transmit off or a restart loop; slow blink
  for unreviewed high events, needs training, training running or card nearly
  full; otherwise steady. Fast wins over slow, slow over steady (STS-1).
* ``contents(state, utc)``: the ``status-1`` file (``docs/examples/status.json``
  fields, plus ``training_coverage``, ``transmit`` and ``vin_status``).
* ``Status.update(state, now_mono, utc)``: sets the light when it changes and
  returns the file bytes to write through ``store`` at a state change, or at
  most every ``logging.sync_interval_s`` while the contents change.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from j1939logger.platform.interface import Platform

__all__ = ["State", "Status", "light", "contents"]


@dataclass(frozen=True)
class State:
    """What ``session`` knows that the status file and the light show."""

    state: str  # a Logger state value
    session: Optional[int] = None
    bitrate: Optional[int] = None
    logger_sa: Optional[int] = None
    unreviewed_high: int = 0
    fault: Optional[str] = None  # the current high fault, if any
    card_used_pct: Optional[float] = None
    card_nearly_full: bool = False
    clock_valid: bool = False
    clock_source: Optional[str] = None
    untrained: bool = False
    retrieved: Sequence[str] = ()
    retrieved_partial: Sequence[str] = ()
    training_coverage: Optional[Mapping[str, Any]] = None
    config: Optional[str] = None
    inventory: Optional[str] = None
    library: Optional[str] = None
    transmit: str = "on"  # "on", or "off: <reason>"
    vin_status: Optional[str] = None
    restart_loop: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)


def light(s: State) -> str:
    """The one light's pattern (STS-1): off, fast, slow or steady."""
    if s.state in ("starting", "detecting bit rate"):
        return "off"
    if (
        s.fault is not None
        or s.vin_status == "mismatch"
        or s.transmit != "on"
        or s.restart_loop
        or s.state == "fault"
    ):
        return "fast"
    if (
        s.unreviewed_high > 0
        or s.state in ("needs training", "training")
        or s.untrained
        or s.card_nearly_full
    ):
        return "slow"
    return "steady"


def contents(s: State, utc: Optional[str]) -> dict[str, Any]:
    """The ``status-1`` file contents (STS-3)."""
    return {
        "format": "status-1",
        "utc": utc,
        "state": s.state,
        "light": light(s),
        "session": s.session,
        "bitrate": s.bitrate,
        "logger_sa": s.logger_sa,
        "unreviewed_high": s.unreviewed_high,
        "fault": s.fault,
        "card_used_pct": s.card_used_pct,
        "card_nearly_full": s.card_nearly_full,
        "clock_valid": s.clock_valid,
        "clock_source": s.clock_source,
        "untrained": s.untrained,
        "retrieved": list(s.retrieved),
        "retrieved_partial": list(s.retrieved_partial),
        "training_coverage": dict(s.training_coverage) if s.training_coverage else None,
        "config": s.config,
        "inventory": s.inventory,
        "library": s.library,
        "transmit": s.transmit,
        "vin_status": s.vin_status,
        **dict(s.extra),
    }


class Status:
    def __init__(self, platform: Platform, settings: Mapping[str, Any]) -> None:
        self._platform = platform
        self._interval = float(settings.get("logging.sync_interval_s", 2))
        self._light: Optional[str] = None
        self._last_state: Optional[str] = None
        self._last_body: Optional[dict[str, Any]] = None
        self._last_write = float("-inf")
        self.light_changes: list[str] = []

    @property
    def pattern(self) -> Optional[str]:
        return self._light

    def update(self, s: State, now_mono: float, utc: Optional[str]) -> Optional[bytes]:
        """Set the light if it changed; the status file bytes when they should be written."""
        pattern = light(s)
        if pattern != self._light:
            self._light = pattern
            self.light_changes.append(pattern)
            self._platform.set_light(pattern)
        body = contents(s, None)
        changed_state = s.state != self._last_state
        if body == self._last_body and not changed_state:
            return None
        if not changed_state and now_mono - self._last_write < self._interval:
            return None
        self._last_state = s.state
        self._last_body = body
        self._last_write = now_mono
        return (json.dumps({**body, "utc": utc}, indent=2) + "\n").encode("utf-8")
