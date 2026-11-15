"""session: the session lifecycle and the main loop (docs/modules.md section 4, contract v1).

Layer 4; frozen for step 2, with the step 3 rules of DC-12.

Lifecycle:

* ``start()`` (power-on) opens capture listen-only and opens a session.
* Bit rate (NP-1, NP-2, NP-17): listen-only until ``platform.bitrate_check()``
  confirms 250000 or 500000, tried on every loop; after ``can.bitrate_fault_s``
  without one, a high fault (once). Once confirmed, capture switches to normal
  mode and, unless the restart guard holds, ``transmit`` is enabled, the
  logger claims an address (``address``) and the request schedule starts
  (``requests``).
* The ``session_start`` header is written once the claim has settled
  (``address.claim_wait_ms`` after it was sent), so it carries the claim
  result; records produced before then are written right after it. Without a
  confirmed bit rate the header is written at once.
* Each ``step()`` kicks the watchdog (STS-18), reads frames, and runs
  ``decode`` -> ``address`` -> ``requests`` -> ``clock`` -> ``detect`` ->
  ``eventlog``; a ``connection_start`` is synced at once (DET-16) and its
  device is asked for its identity (NP-13). ``transmit`` sends what the
  limits allow.
* Bus-off or TX error-passive (``decode.bus_state``) turns transmit off for
  the session (NP-3).
* Restart guard (NP-19, DC-12): ``state.json`` keeps ``unclean_starts``; when
  ``restart_guard.count`` fall within ``restart_guard.window_min`` the session
  starts listen-only with transmit off and a high fault "restart loop;
  transmit disabled". A clean session end clears the list.
* VIN (NP-12, DC-12): the header has ``vin_status`` "pending"; a ``vin_check``
  record follows the VIN reply, NACK or no reply.
* Key-off after ``session.end_silence_s``; a new session on the next frame;
  roll-over after ``logging.session_rollover_h`` (LOG-2, LOG-17, DC-10, DC-11).
  ``transmit``, ``address`` and ``requests`` are new for each session.

Numbering and the chain (LOG-5, DC-10): the next session number is one more
than the higher of ``state.json`` and the newest session file; the first
``prev`` is the last complete hash of the newest file, or 64 zeros (a new card
when a state file exists). Previous end: clean, the diagnostic log's restart
cause, or power loss with ``bytes_cut_off``.
"""

from __future__ import annotations

from j1939logger.session.core import Session
from j1939logger.session.files import (
    SW_VERSION,
    SessionFile,
    card_files,
    operator_key_fingerprints,
    session_files,
    settings_from_config,
)

__all__ = [
    "Session",
    "settings_from_config",
    "SessionFile",
    "session_files",
    "SW_VERSION",
    "card_files",  # j1939cmd answers retrieve_list with it when the service is down
    "operator_key_fingerprints",
]
