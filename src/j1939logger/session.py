"""session: the main loop (step 1 minimal form, DC-9).

Layer 4. Runs, for each batch of frames: ``capture`` -> ``decode`` ->
``clock`` (Time/Date) -> ``detect`` -> ``eventlog``, and syncs at once after
a ``connection_start`` (DET-16). Listen-only throughout: nothing is sent in
step 1.

Built in step 2 against the frozen contract: ``session_start`` and
``session_end``, parts and roll-over, ``state.json`` and numbering, the
start-up self-check, watchdog kicks, the restart guard and key-off.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any, Optional

from j1939logger.capture import Capture
from j1939logger.clock import Clock
from j1939logger.decode import decode, new_state
from j1939logger.detect import Detect, InventoryEntry
from j1939logger.eventlog import ZERO_HASH, EventLog
from j1939logger.platform.interface import Platform
from j1939logger.types import PlatformError

__all__ = ["Session", "settings_from_config"]

# The config keys step 1 reads (DC-9); the config module validates them from step 2.
STEP1_KEYS = (
    ("can", "rx_buffer_bytes"),
    ("logging", "raw_before_s"),
    ("limits", "tp_sessions"),
    ("clock", "max_skew_min"),
    ("classify", "wake_window_s"),
)


def settings_from_config(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The step 1 settings from a cfg-1 config, as ``section.key`` -> value."""
    out = {}
    for section, key in STEP1_KEYS:
        try:
            out[f"{section}.{key}"] = cfg[section][key]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"config is missing {section}.{key}") from exc
    return out


class Session:
    def __init__(
        self,
        platform: Platform,
        settings: Mapping[str, Any],
        inventory: Optional[Mapping[int, InventoryEntry]],
        session: int = 1,
        prev: str = ZERO_HASH,
    ) -> None:
        self._platform = platform
        self._session = session
        self.clock = Clock(platform, float(settings["clock.max_skew_min"]))
        self.capture = Capture(
            platform,
            rx_buffer_bytes=int(settings["can.rx_buffer_bytes"]),
            raw_before_s=float(settings["logging.raw_before_s"]),
        )
        self._decode_state = new_state(int(settings["limits.tp_sessions"]))
        self.detect = Detect(self.clock, inventory, float(settings["classify.wake_window_s"]))
        sessions = platform.paths().card / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        stamp = self._stamp()
        self.eventlog = EventLog(
            platform, self.clock, sessions / f"s{session:06d}_{stamp}.jsonl", session, prev
        )
        self._stop = threading.Event()

    def _stamp(self) -> str:
        wall = self.clock.now().wall_utc
        return wall.strftime("%Y%m%dT%H%M%SZ") if wall is not None else "unknown"

    def start(self) -> None:
        self.capture.start(listen_only=True)

    def step(self, max_n: int = 1000) -> int:
        """Process the frames already received; returns how many. Raises PlatformError."""
        frames = self.capture.read_batch(max_n)
        if not frames:
            return 0
        msgs, _, _, self._decode_state = decode(frames, self._decode_state, logger_sa=None)
        for msg in msgs:
            records = self.clock.on_time_date(msg) + self.detect.on_message(msg)
            for record in records:
                self.eventlog.append(record)
                if record.type == "connection_start":
                    self.eventlog.sync_now()  # DET-16
        return len(frames)

    def run(self, idle_s: float = 0.01) -> Optional[PlatformError]:
        """Loop until ``stop()``; returns the PlatformError that ended it, if any."""
        try:
            while not self._stop.is_set():
                if self.step() == 0:
                    self._stop.wait(idle_s)
        except PlatformError as exc:
            return exc
        finally:
            self.capture.stop()
            self.eventlog.sync_now()
            self.eventlog.close()
        return None

    def stop(self) -> None:
        self._stop.set()
