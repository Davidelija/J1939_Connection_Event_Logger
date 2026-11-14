# Module contracts

Design guidance for each module: what it is for, what goes in and comes out, what it owns, how it fails, and where tests attach. Developers build to these contracts; test-script writers write tests against them without needing to know how a module works inside.

- **Authority:** the requirements win over this file, and `docs/log-format.md` wins on any record or field detail (`CLAUDE.md`). This file adds the boundaries between modules.
- **Versions:** every contract starts at v1 (DC-0). A change to a module's inputs, outputs, errors or config keys raises its version and needs an entry in `docs/design-changes.md`.
- **Freeze:** before a build step starts, the contracts it touches are frozen for that step (table below). Tests for the step are written against the frozen version.
- **Names in code:** types below are written as Python dataclasses; field names are the contract. Internal helpers are free.

## 1. Shared types (`src/j1939logger/types.py`) — frozen for step 1

Defined once, in build step 1, and imported everywhere. Tests build fixtures from these.

**Python 3.9 (DC-1, DC-6):** `types.py` starts with `from __future__ import annotations` and writes optional fields as `Optional[X]`, because the shared types are evaluated at run time (`typing.get_type_hints`, Hypothesis strategies). Never use `X | None` in code evaluated at run time (`isinstance` checks, casts, `typing.get_type_hints`).

```python
from __future__ import annotations

@dataclass(frozen=True)
class Frame:              # one raw CAN frame from capture
    ts_kernel: float      # kernel receive time, seconds (SO_TIMESTAMP, wall clock at receipt)
    ts_mono: float        # ts_kernel converted to monotonic time: ts_kernel - (wall - mono), sampled at read time;
                          # not the time the batch was read (valid because the clock is never stepped, X27)
    can_id: int           # 29-bit or 11-bit identifier
    extended: bool        # True for 29-bit
    remote: bool
    error: bool           # error frame (flags in data)
    data: bytes           # 0 to 8 bytes
    own: bool             # sent by this logger (loopback)

@dataclass(frozen=True)
class J1939Msg:           # one J1939 message after decode (single frame or reassembled transfer)
    ts_mono: float        # time of the first frame (for transfers: the RTS or BAM)
    ts_kernel: float
    priority: int
    pgn: int
    sa: int
    da: int               # 255 for broadcast
    data: bytes           # full payload, up to 1785 bytes
    via_tp: bool
    own: bool             # sent by this logger
    reply_to_logger: bool # addressed to the logger's own address

@dataclass(frozen=True)
class Name:               # the 64-bit NAME and its decoded fields (raw numbers, IDN-1)
    value: int
    aac: int; industry_group: int; vs_instance: int; vehicle_system: int
    function: int; function_instance: int; ecu_instance: int
    mfr_code: int; identity: int

@dataclass(frozen=True)
class ClockReading:
    wall_utc: Optional[datetime]   # None when no valid source
    mono: float
    source: str                 # "rtc" | "vehicle" | "elapsed" (requirements enum)
    valid: bool

@dataclass
class Record:             # a log record before eventlog adds written, prev and hash
    type: str             # record type from docs/log-format.md
    sev: str              # "info" | "notice" | "high"
    utc: Optional[datetime]  # event time
    veh_time: Optional[datetime]
    fields: dict          # the type-specific fields, exactly as in docs/log-format.md
    conn: Optional[int] = None
    event_id: Optional[str] = None   # "<session>-<n>", assigned by eventlog for events
# eventlog adds rec, written, prev and hash, and assigns event_id. Every utc comes from clock.to_utc(ts_mono), never from Frame.ts_kernel directly (X27).

@dataclass
class Connection:         # one external device's connection, owned by detect
    conn: int
    key: tuple            # ("name", value) or ("sa", address) for a device that never claims
    sa: int
    name: Optional[Name]
    start_mono: float
    last_mono: float
    category: str         # Category enum in the requirements (vehicle ECU not in baseline, trailer device, external device ...)

@dataclass(frozen=True)
class TxRequest:          # a frame the logger asks transmit to send (DC-8); only transmit sends
    pgn: int
    da: int               # destination address, 255 for global
    data: bytes
    kind: str             # "protocol" (claim, NACK, ACK, CTS, EOMA, Abort) or "request"

class PlatformError(Exception):   # the only exception type platform raises
    kind: str             # a value from the Kind column of docs/errors.md (the single list of fault kinds)
```

**Diagnostic log conventions** (`admin`, LOG-20): one line per event, `<utc> <level> <module> <message>`, levels `error`, `warning`, `info`, `debug`; a repeated error is logged once with a count; no evidence data (NAMEs, VINs, frames) goes in the diagnostic log, only references such as `conn` or `event_id`.

Further enumerations (categories, severities, clock sources, make sources, approval kinds, end reasons) come from the requirements' Enumerated values table. Put them in `types.py` as string constants with those exact spellings.

## 2. Layering

Modules may only call modules in the same layer or below. Nothing imports `main`. CI checks this with an import-linter rule.

| Layer | Modules | Rule |
|---|---|---|
| 5. Entry points | `main` (with `cmdserver`), `j1939cmd`, `j1939ctl` (laptop), `verify_chain` (tool) | Wire everything together; no logic of their own beyond parsing and dispatch |
| 4. Orchestration | `session`, `admin` | Own the session lifecycle and the main loop |
| 3. Logic | `detect`, `monitor`, `identify`, `address`, `requests`, `inventory`, `retention`, `status` | No I/O except through layer 1 or 2 interfaces; testable with fakes. The one exception: `status` may call `platform.set_light()`, a hardware call that touches no file |
| 2. Pure | `decode`, `config` (validation of config, inventory and library files) | No I/O, no clock, no threads |
| 1. Services | `capture`, `transmit`, `eventlog`, `store`, `rawcap`, `clock` | The only modules that touch sockets or files, apart from `platform` |
| 0. Hardware | `platform` | The only hardware- or Beacon-specific code (rule 12) |

Safety-critical paths (`transmit`, allow-list validation in `config`, hashing in `eventlog`, and `platform`) need a review by Vaughan Lynn or Elijah Umaru on every change (`.github/CODEOWNERS`), not only CI.

Ownership rules that the layering enforces:
- Only `transmit` sends on the bus (rule 4).
- Only `capture` receives from the bus (rule 6).
- Only `eventlog` writes session files; only `store` writes supporting files (status, inventory and config versions, library (which holds the manufacturer list, IDN-2), `state.json`); only `rawcap` writes raw captures. Only the service process writes logger state (STS-23, rule 15).
- Only `clock` (through `platform`) gives time; no module calls `time.time()` or `datetime.now()` directly (rule 14).

## 3. Threads and data flow

- **Capture thread** (`capture`): reads frames into the ring buffer. Never blocks on anything else.
- **Main loop** (`session`): takes frame batches from the ring, runs `decode`, then `address`, `detect`, `monitor`, `identify` and `requests` in that order for each message, and hands records to `eventlog` and supporting-file writes to `store`. Applies one command from `cmdserver` between batches.
- **Sync thread** (`eventlog`): syncs files every `logging.sync_interval_s`, and at once when asked (connection\_start).
- **Command thread** (`cmdserver`): accepts socket connections and queues requests for the main loop; never touches state itself.

```
platform → capture ──Frame ring──▶ session main loop ──▶ decode ──J1939Msg──▶ address · detect · monitor · identify · requests
                                        │                                          │ Records                 │ TxRequest
                                        │◀──── cmdserver queue                      ▼                         ▼
                                        └──────────────────────────────────▶ eventlog (+ sync thread)    transmit → platform
                                                                              rawcap (reads the ring)
```

## 4. Module contracts

### platform  (v2, layer 0) — frozen for step 1
- **Purpose:** the hardware boundary. Desktop (`vcan0`) and Beacon implementations; tests use the desktop one with a fault plan.
- **Interface:** `open_can(listen_only: bool) -> socket`; `bitrate_check() -> int | None`; `set_light(pattern: str)` ("steady" | "slow" | "fast" | "off"); `now() -> ClockReading`; `rtc_ok() -> bool`; `on_wake() -> (wake_mono, ready_mono)`; `watchdog_kick()`; `paths() -> Paths` (card, flash, keys; `Paths` is defined in `platform/interface.py`, DC-6); `fault(op: str)` (v2, DC-5), called by layer 1 modules just before each operation in `FAULT_OPS` (`can_recv`, `can_send`, `card_write`, `card_sync`, `flash_write`); it raises a planned fault on the desktop and does nothing on hardware.
- **Time:** `now()` reports `rtc` when the real-time clock is valid, otherwise `elapsed` with no wall time; only `clock` reports `vehicle`, from its own offset (DC-6).
- **CAN input:** raw SocketCAN by default; `python-can` only as an optional extra inside this layer (X22).
- **Errors:** raises only `PlatformError` with a `kind` from `docs/errors.md`; a bad argument (an unknown light pattern or operation) is a programming error and raises `ValueError` (DC-6).
- **Test seam:** `DesktopPlatform(fault_plan=[(at_mono, kind, args), ...], clock=FakeClock())` controls time and injects the platform's faults (DC-5): `can_missing`, `no_bitrate`, `rtc_invalid`, `clock_jump`, and through `fault(op)` `can_down`, `enobufs`, `enospc`, `erofs`, `eio`, `card_removed`, `state_unwritable` and `slow_sync`. A fault is active from `at_mono` for `args["for_s"]` seconds, or for the rest of the run. Other kinds are injected by traffic, the harness or test setup (DC-5).
- **Requirements:** PLT-1 to PLT-8, HW-7, HW-8, STS-1, STS-18. **Not responsible for:** any J1939 logic.

### clock  (v2, layer 1) — frozen for step 1; v2 (DC-10)
- **Purpose:** one source of time and its validity.
- **Inputs:** `platform.now()`; Time/Date replies (`J1939Msg`, PGN 65254) from the main loop.
- **Outputs:** `now() -> ClockReading`; `mono() -> float`; `to_utc(ts_mono) -> datetime | None` (the only way any module turns a frame or event time into a record's `utc`; None while the source is `elapsed`, when `eventlog` writes `elapsed_s` instead, DC-10); `veh_time(ts_mono) -> datetime | None` (vehicle time for an event from the Time/Date offset, whole seconds, None before the first reply; v2, DC-10); `elapsed_s(ts_mono) -> float` (seconds since wake, DC-10); a `time_sync` or `fault` `Record` when the source changes or vehicle time disagrees by more than `clock.max_skew_min`.
- **State:** vehicle-time offset; never sets the system clock (LOG-16). The kernel sets the system clock from the RTC at boot (`hctosys`, checked in step 2a), so kernel frame timestamps are right from the first frame. The logger checks `rtc_ok()` itself and records `clock_source`; it never waits for the clock.
- **Config:** `clock.max_skew_min`. **Requirements:** LOG-16. **Test seam:** `FakeClock` with `advance(s)` and `jump(s)`.

### config  (v1, layer 2) — frozen for step 2
- **Purpose:** validate and version the config; also validates the inventory and library files.
- **Inputs:** a config file (JSON) and the previous active version, loaded by `store`; inventory (`inv-1`) and library (`lib-1`) contents from `store`.
- **Outputs:** `Config` (typed, read-only) or `ConfigError(reasons)`; `validate_inventory(data) -> Inventory | InventoryError`; `validate_library(data) -> Library | LibraryError`; `config_change` / `config_rejected` `Record` with changed fields and whether the change weakens detection.
- **Rules:** unknown or missing keys rejected; additions to `requests.allow_list` or `transmit.allow_list` rejected; `detection.move_grace_s` over 5 s rejected; detection-weakening changes need `--confirm` (STS-9).
- **Config:** all keys in the requirements' Configuration table. **Requirements:** LOG-13, STS-9. **Test seam:** pure functions `validate(new, old) -> Config | ConfigError`, `validate_inventory` and `validate_library`.

### capture  (v2, layer 1) — frozen for step 1; v2 (DC-12)
- **Purpose:** frames in, timestamped records out (rule 6).
- **Inputs:** `platform.open_can()`; mode changes from `session` (listen-only, normal): `capture` closes the socket and calls `open_can(listen_only=False)` (DC-6).
- **Rules:** sets the receive buffer from `can.rx_buffer_bytes` (`SO_RCVBUFFORCE`) and reads it back (DC-6); calls `platform.fault("can_recv")` before each receive (DC-5).
- **Outputs:** `read_batch(max_n) -> list[Frame]`, which never waits: it returns the frames already in the ring, up to `max_n`, oldest first (DC-8); `window(start_mono, end_mono) -> list[Frame]` for `rawcap`, including frames at both ends (DC-8); `stats() -> CaptureStats` with `kernel_drops: int` (from SO\_RXQ\_OVFL), `rx_buffer_bytes: int` (size read back) and `frames: dict[str, int]` (counts by type, keys `extended`, `standard`, `remote`, `error`) (DC-8); `transmit_handle()` (v2, DC-12): a send-only handle on capture's own socket, for `transmit` alone, so the logger's frames come back marked `own` (`MSG_CONFIRM`); capture itself never sends.
- **Errors:** `PlatformError` from the socket goes to `session`; capture never raises on frame content and never syncs files.
- **Ring length:** `logging.raw_before_s` + 2 s, so the main loop can catch up after a sync stall without losing the pre-event window.
- **Performance budget:** frames/s at 100% load at 500 kbit/s with no kernel drops, and µs per frame: to be measured in SC-9 (build step 8) and recorded here.
- **Config:** `can.*`, `logging.raw_before_s`. **Requirements:** SC-2, NP-1 to NP-3, NP-17, LOG-15. **Test seam:** `DesktopPlatform` plus a candump replay on `vcan0`; the ring can be filled directly in unit tests.

### decode  (v2, layer 2) — frozen for step 1; v2 (DC-12)
- **Purpose:** raw frames to J1939 messages.
- **Inputs:** `list[Frame]`; the logger's current address.
- **Outputs:** `list[J1939Msg]`; `DecodeStats` with `non_j1939: dict[str, int]` (frames by type, keys `standard`, `remote`, `error`), `tp_closed: dict[str, int]` (transport sessions closed, by reason), `malformed: dict[str, int]` (by reason) and `etp_seen: int` (DC-8); `TxRequest`s for transfers addressed to the logger: CTS when an RTS is accepted and for each further window, EOMA when it completes, Connection Abort when it is rejected (v2, DC-12); `bus_state(frame) -> str | None` (v2, DC-12), a pure helper giving "bus_off" or "error_passive" (TX error-passive) from an error frame's controller state.
- **State:** a `DecodeState` that only `decode` reads or changes; callers pass it back unchanged (DC-8). It holds the open TP sessions, at most `limits.tp_sessions`; ETP is recognized, not reassembled.
- **Errors:** never raises on input (SC-12a).
- **Performance budget:** µs per frame at 100% load: to be measured in SC-9 and recorded here.
- **Config:** `limits.tp_sessions`. **Requirements:** NP-9, NP-15, IDN-1, DET-10, DET-19, SC-12a. **Test seam:** pure `decode(frames, state) -> (msgs, stats, tx, state)`; property tests with Hypothesis.

### transmit  (v1, layer 1) — frozen for step 3
- **Purpose:** the only path to the bus.
- **Inputs:** `TxRequest(pgn, da, data, kind)` (shared types, §1; DC-8) from `address`, `requests` and `decode`; `kind` is "protocol" (claim, NACK, ACK, CTS, EOMA, Abort) or "request".
- **Outputs:** frames to `platform`; `TxResult` per request (sent, refused with reason); a `fault` `Record` and `enabled = False` for the rest of the session on any breach or unexpected error; counts for `logger_tx` in `session_end`.
- **Rules:** allow-list (`transmit.allow_list`, `requests.allow_list`), 10 frames/s, one outstanding request per destination, protocol responses jump the queue; nothing sent before a bit rate is confirmed or while the restart guard holds; calls `platform.fault("can_send")` before each send (DC-5). Sends only through `capture.transmit_handle()` (DC-12).
- **Rate cap (DC-12):** at most `transmit.max_frames_per_s` frames in any sliding 1 s window, counting every frame sent, protocol frames included. Protocol frames (claim, NACK, CTS, EOMA, Abort) go ahead of queued requests. A frame that would exceed the cap waits in the queue; it is not a breach.
- **Outstanding requests (DC-12):** a second request to a destination is held until `requests` calls `release(da)` on a reply, NACK or timeout; a global request counts as destination 255.
- **Breach (DC-12, NP-9, NP-18):** any of these is refused, never sent, and turns transmit off for the session with a high `fault` (`tx_breach`): a PGN outside `transmit.allow_list`; a Request (59904) for a PGN outside `requests.allow_list`; an Address Claim (60928) with any NAME but the logger's; an Acknowledgment (59392) that is not a NACK; a TP.CM (60416) that is not CTS, EOMA or Abort; a `TxRequest.kind` that does not match its PGN. `disable(reason)` turns transmit off for the session on bus-off, error-passive (NP-3) or an `ENOBUFS` send error (NP-18); it never turns back on in that session (rule 4).
- **Config:** `transmit.*`, `requests.allow_list`. **Requirements:** NP-3, NP-9, NP-16 to NP-19. **Test seam:** a recording socket from `DesktopPlatform`; the A3 witness test on hardware.

### address  (v1, layer 3) — frozen for step 3
- **Purpose:** the logger's own address claim (it always concedes).
- **Inputs:** `J1939Msg` (Address Claim, Request for Address Claim, requests addressed to the logger); the inventory's addresses; the session's claimed addresses (from `detect`).
- **Outputs:** `TxRequest`s (claim, Cannot Claim, answer to Request for Address Claim, NACK); the logger's current address or None; `address_conflict` `Record` when it loses its claim.
- **Rules:** a Commanded Address (65240) directed at the logger's NAME is ignored (NP-8). Address choice (DC-12): from `address.claim_from` down to `address.claim_down_to`, skipping inventory addresses, addresses claimed this session and `address.reserved`. The lower NAME wins a contest; the logger's NAME is the highest possible, so it always concedes. `address.claim_wait_ms` after a claim before other traffic (NP-6). After `address.claim_retries` + 1 losses, Cannot Claim from the null address (254) and receive-only for the session (NP-7). Answers Request for Address Claim; NACKs any other request addressed to the logger.
- **Config:** `address.*`. **Requirements:** NP-4 to NP-8, DET-4. **Test seam:** feed messages and a `FakeClock`; check the `TxRequest` sequence.

### requests  (v1, layer 3) — frozen for step 3
- **Purpose:** the logger's scheduled and identity requests.
- **Inputs:** session start; new connections from `detect`; replies and NACKs (`J1939Msg`); `FakeClock` time.
- **Outputs:** `TxRequest`s (sweep, Time/Date, VIN to `requests.vin_sa`, Component, Software and ECU ID); `RequestOutcome(conn, pgn, outcome, value)` to `identify`; `sweep` `Record`s; "first sweep complete" signal to `detect`.
- **Rules:** 1.25 s timeout, one retry; addresses already held by a known NAME are not asked again.
- **Config:** `requests.*`. **Requirements:** NP-11 to NP-14, DET-14. **Test seam:** messages plus clock in, `TxRequest`s and outcomes out.

### detect  (v1, layer 3) — frozen for step 4
- **Purpose:** decide when a device connects, moves or ends.
- **Inputs:** `J1939Msg`; the inventory; the first-sweep signal from `requests`; `FakeClock` time.
- **Outputs:** `Connection` objects (opened, updated, closed); `Record`s: `connection_start` (flagged for immediate sync), `connection_end`, `address_change`, `address_conflict` (including same NAME at two addresses); the session's address-to-NAME map for other modules.
- **Rules:** keyed by NAME, or by SA for a device that never claims; first-sweep wait (`detection.first_sweep_wait_s` when no sweep can be sent); move grace; 60 s silence end.
- **Config:** `detection.silence_end_s`, `detection.move_grace_s`, `detection.first_sweep_wait_s`, `limits.*`. **Requirements:** DET-1 to DET-6, DET-15 to DET-17. **Test seam:** message list plus inventory plus clock in, records out; the X42 fixtures.

### monitor  (v1, layer 3) — frozen for step 4
- **Purpose:** what each connected device does.
- **Inputs:** `J1939Msg` with its `Connection`; the inventory's PGNs per NAME.
- **Outputs:** per-connection PGN table, first `detection.requests_kept` requests, DM activity, ETP transfers (fields for `connection_end`); `control_flag` and `known_device_new_pgn` `Record`s; a raw-capture trigger to `rawcap`.
- **Config:** `detection.control_pgns`, `detection.requests_kept`, `detection.known_device_new_pgn`, `limits.pgns_per_conn`. **Requirements:** DET-7 to DET-12. **Test seam:** messages for one connection in, table and records out.

### identify  (v1, layer 3)
- **Purpose:** what kind of device it is.
- **Inputs:** `Connection` with its NAME; `RequestOutcome`s; the monitor's requested-PGN set as it stands when identification completes, and again at connection end; the device library and manufacturer list (validated by `config`).
- **Outputs:** an `identification` `Record` (category, type guess, make, model, make\_source, confidence, source, candidates on a type tie); the severity for the connection; at connection end, a recalculated `Identification`, which `detect` puts in `connection_end` as `final_identification` only if the type, make or model changed (IDN-4).
- **Rules:** rules first (DET-13, DET-18), then the IDN-4 score (function-code gate, Jaccard minus never-PGN penalties, tie margin); make and model precedence (IDN-3).
- **Config:** `classify.*`, `identify.tie_margin`. **Requirements:** DET-13, DET-18, IDN-2 to IDN-7. **Test seam:** pure `identify(conn, outcomes, pgns, library) -> Identification`; table-driven tests.

### inventory  (v1, layer 3)
- **Purpose:** the known-good devices for this truck.
- **Inputs:** the active inventory (loaded by `store`, validated by `config`); training observations; operator commands (train finish, approve, remove, reject) from `session`.
- **Outputs:** `Inventory` (read-only view: entries by NAME and by never-claiming SA, PGNs per entry); new inventory versions, handed to `store`; `approval`, `rejection`, `inventory_remove` `Record`s.
- **Errors:** a corrupt file gives `InventoryError` from validation; `session` then runs untrained (STS-19).
- **Config:** `training.*`. **Requirements:** TRN-2 to TRN-7, TRN-10 to TRN-15. **Test seam:** pure operations on an `Inventory` value (file round-trip tests belong to `store`).

### eventlog  (v1, layer 1) — frozen for step 1 (append only); frozen for step 2
- **Frozen for step 1 (append only, DC-8):** appending a `Record` (adds `rec`, `written`, `prev` and `hash`; assigns `event_id`), the hash rule in `docs/log-format.md`, one `write()` per record to an `O_APPEND` file, `sync_now()` and the last hash. Session parts, roll-over and rebuilding the last hash after a crash freeze with the rest of `eventlog` in step 2.
- **Purpose:** append records to the session file and keep the hash chain (session files only).
- **Inputs:** `Record`s from any layer 3 or 4 module via `session`; `sync_now()` requests; the starting `prev` from `session`.
- **Outputs:** lines in the session file (adds `written`, `prev`, `hash`, assigns `event_id`); the last hash.
- **Rules:** one `write()` per record to an `O_APPEND` file; directory synced after each rename; sync on its own thread; after a crash, the last hash is rebuilt from the last complete line of the newest session file, which wins over `state.json`; `state.json` gives the last hash only for the LOG-5 cases without session files (DC-10); records with `clock_source` `elapsed` carry `elapsed_s` and null `utc` and `written` (DC-10); calls `platform.fault("card_write")` and `platform.fault("card_sync")` before each write and sync (DC-5).
- **Errors:** storage errors become a `fault` `Record` and a fast blink (LOG-22); logging never crashes the logger.
- **Config:** `logging.*`, `storage.*`. **Requirements:** LOG-3 to LOG-5, LOG-7 to LOG-9, LOG-23. **Test seam:** a temporary directory; `verify_chain` over the result.

### store  (v1, layer 1) — frozen for step 2
- **Purpose:** load and write every supporting file.
- **Inputs:** `platform.paths()`; contents to write from `session` (status, new inventory and config versions, `state.json`); the free list from `retention`.
- **Outputs:** `load(kind, version=None) -> bytes | None` for status, inventory, config, library and state (the manufacturer list is part of the library, IDN-2; DC-10); `write_atomic(kind, name, data)` (temporary file, sync, rename, directory sync); `versions(kind)`; `usage() -> CardUsage`; `free(files)`.
- **Rules:** the only writer of supporting files; never writes session files or raw captures; frees only what `retention` lists; `state.json` is on internal flash, everything else on the card; calls `platform.fault()` before each write and sync (`card_write`, `card_sync`, `flash_write`, DC-5).
- **Errors:** storage errors become a `fault` `Record` (LOG-22); a missing file loads as None; leftover temporary files are ignored (LOG-23).
- **Config:** `storage.*`. **Requirements:** LOG-5 (state file), LOG-13, LOG-23, TRN-6, STS-3. **Test seam:** a temporary directory; file round-trip tests; write errors from the fault plan.

### rawcap  (v1, layer 1)
- **Purpose:** raw candump windows around events.
- **Inputs:** triggers (connection start, control flag) with `conn`, `event_id` and `ts_mono`; `capture.window()`.
- **Outputs:** `s<session>_c<conn>_e<event>.log` covering −`logging.raw_before_s` to +`logging.raw_after_s`; the file name for the record's `raw_capture` field.
- **Rules:** calls `platform.fault("card_write")` before each write (DC-5).
- **Config:** `logging.raw_before_s`, `logging.raw_after_s`, `limits.raw_mb_per_session`. **Requirements:** LOG-10. **Test seam:** check every window contains its record's `utc`.

### retention  (v1, layer 3)
- **Purpose:** keep the card from filling.
- **Inputs:** card usage from `store.usage()`; the retrieved list; `storage.*`.
- **Outputs:** which files to free, in the agreed order (only retrieved raw captures and diagnostic files; never session files, rule 9), carried out by `store.free()`; `fault` `Record`s (card nearly full: notice; card full: high).
- **Requirements:** LOG-11, LOG-22. **Test seam:** a temporary directory with a fake size limit.

### status  (v1, layer 3)
- **Purpose:** the status file and the light.
- **Inputs:** state from `session` (unreviewed events, training needed or running, faults, card nearly full, transmit off, restart loop, VIN mismatch).
- **Outputs:** the status file contents (`status-1`), written by `store`; `platform.set_light()` with the priority fast > slow > steady (the layer 3 exception in section 2).
- **Requirements:** STS-1 to STS-3. **Test seam:** state in, file contents and light pattern out (table-driven).

### session  (v1, layer 4) — frozen for step 2
- **Purpose:** the session lifecycle and the main loop.
- **Inputs:** wake from `platform`; frames from `capture`; commands from `cmdserver`; the restart guard state; `state.json` from `store` (logger ID, last session number, last hash).
- **Outputs:** `session_start` and `session_end` `Record`s; session files and parts; calls into every layer 3 module in order; watchdog kicks.
- **Performance budget:** main-loop latency from frame receipt to record, against DET-16's 2 s: to be measured in SC-9 and recorded here.
- **Rules:** `state.json` is written at session start and after each session part; the next session number is one more than the higher of `state.json` and the newest session file on the card; a blank card with a state file is a new card (`new_card: true`, first `prev` 64 zeros); a card with sessions and no (or a corrupt) state file continues numbering and the chain from the card; a blank card with no state file is a new logger (LOG-5); 30 s silence key-off (`session.end_silence_s`); after `session_end` the logger waits listen-only and starts a new session (wake cause "CAN activity") on the next frame (DC-10); roll-over (`logging.session_rollover_h`): `session_end` with reason "session roll-over", then a new part starting with a repeated `session_start` (`part` + 1, same session number) (DC-10); start-up self-check (STS-19); restart guard (NP-19, DC-12): `state.json` keeps `unclean_starts`, the wall times (UTC, or null without a valid clock) of recent unclean starts; the guard holds when `restart_guard.count` of them fall within `restart_guard.window_min` (null times count as inside), and clears after a clean session end or an operator `restart`. Bit rate (NP-1, NP-17, DC-12): listen-only until `platform.bitrate_check()` confirms 250000 or 500000, retried, with a fault after `can.bitrate_fault_s`; then `capture.set_mode(listen_only=False)` (NP-2). VIN (NP-12, DC-12): `session_start` is written at ready with `vin` null and `vin_status` "pending"; a `vin_check` record follows the reply, NACK or timeout.
- **Previous session end (LOG-12, LOG-18, STS-18; DC-10):** clean if the newest session file ends with `session_end`; otherwise the cause in the diagnostic log's last entry (software restart, watchdog restart); otherwise power loss, with the bytes cut off equal to the length of any incomplete last line.
- **Frames that aren't J1939 (DC-10):** `session_end.frames_not_j1939` uses the log-format keys; `session` maps `DecodeStats.non_j1939["standard"]` to `std_11bit`.
- **Requirements:** LOG-1, LOG-2, LOG-6, LOG-12, LOG-17, LOG-18, TRN-9, NP-19, STS-18, STS-19. **Test seam:** run in-process with `DesktopPlatform` and `FakeClock`; this is the component-test entry point.

### admin  (v1, layer 4)
- **Purpose:** restart, retrain and the diagnostic log. The diagnostic-log writer is built in step 2 in minimal form (`diag/logger.log`, rotated by `diag.max_bytes` and `diag.files`, the conventions in §1), before `admin` freezes in step 7 (DC-10).
- **Inputs:** commands from `session`.
- **Outputs:** `reset` `Record`s; the diagnostic log (separate from evidence, `diag.*`).
- **Requirements:** STS-11, STS-12, LOG-20. **Not built:** move, wipe, library push, update, rollback, roles (Deferred).

### cmdserver  (v1, layer 5, inside `main`)
- **Purpose:** the command socket (STS-23).
- **Inputs:** JSON lines on `/run/j1939-logger/cmd.sock`: `{"proto":1,"cmd":...,"args":{...},"operator":...,"reason":...}`.
- **Outputs:** `{"proto":1,"ok":true,"result":{...}}` or `{"proto":1,"ok":false,"error":"...","next":"..."}`; requests queued for the main loop, one at a time.
- **Errors:** an unknown protocol version, unknown command or bad arguments is refused with a reason; never changes state itself.
- **Test seam:** a socket client in tests; the protocol is the contract.

### j1939cmd  (v1, layer 5, logger side)
- **Purpose:** the program SSH runs for each laptop command.
- **Inputs:** command line from `j1939ctl`; the SSH key fingerprint (`ExposeAuthInfo`); the fingerprint-to-name file.
- **Outputs:** the `cmdserver` reply on standard output (JSON) with an exit code; when the service is down, `status` from the status file and `retrieve` file lists, and "logger not running" for anything that changes state.
- **Requirements:** STS-5, STS-23, LAP-15.

### j1939ctl  (v1, laptop)
- **Purpose:** the operator tool on Windows.
- **Inputs:** the 16 commands in the hand-off command table.
- **Outputs:** plain-word screens, the one prompt pattern (what will change, reason, y/N), exit codes (LAP-15); retrieved folders made read-only; the last hash per logger; the summary report.
- **Requirements:** LAP-1 to LAP-15, LAP-17, STS-7, STS-9. **Test seam:** against a local logger on `vcan0` through `j1939cmd`, as in `demo/run_demo.sh`.

### verify_chain  (v1, tool) — frozen for step 2
- **Purpose:** check a set of session files.
- **Inputs:** a folder of session files; optionally the last hash kept by the laptop.
- **Outputs:** pass, or the first broken or missing record with its line; a replacement card's first record (64 zeros, `session_start` noting "new card") reported as a declared chain break, not a failure; format-version check; a truncated last line reported as truncated, not broken. Exit code 0 on pass.
- **Requirements:** LOG-14, LOG-19, LAP-5, LAP-9. **Test seam:** pure function over files; the session 142 example must pass.

## 5. Test integration contract

Test scripts plug in at four levels. Each level uses only what is listed here, so tests do not depend on how a module is built inside.

| Level | Entry point | What a test supplies | What it checks |
|---|---|---|---|
| 1. Unit | A module's public functions in section 4 | Shared types, `FakeClock`, small in-memory values | Return values and `Record`s |
| 2. Component | `session` run in-process | A fixture folder (below), `DesktopPlatform(fault_plan)`, `FakeClock` | Records written, status file, `TxRequest`s |
| 3. Replay (end to end) | The service on `vcan0`, commands through `j1939cmd` | The same fixture folder, played with `canplayer` | Session file (chain verified), raw captures, inventory, status, command replies |
| 4. Acceptance | `bench/` procedures A1 to A8 | Hardware and the minimum acceptance setup | Results lines in `docs/verification.md` |

**Fixture folder** (`tests/fixtures/<scenario>/`):
- `traffic.log`: candump `-L` format (`(1793975500.118) vcan0 18EEFFF9#...`), the bus as the logger would see it.
- `manifest.json`:

```json
{
  "scenario": "x42-copied-name",
  "requirements": ["DET-4"],
  "config": "cfg-v3.json",
  "config_overrides": {"detection.move_grace_s": 1},
  "inventory": "inv-v2.json",
  "library": "lib-v1.json",
  "clock_start_utc": "2026-11-06T14:02:11.000Z",
  "faults": [{"at_s": 30.0, "kind": "card_removed"}],
  "expect": [
    {"type": "address_conflict", "sev": "high", "fields": {"cause": "same NAME at two addresses"}, "within_s": 2.0},
    {"type": "connection_start", "count": 0}
  ],
  "expect_no_other": ["high"]
}
```

**Matching rules:**
- An expected record matches on `type`, `sev` and the listed fields only; other fields are not compared, so internal changes don't break tests.
- `within_s` is measured from the triggering frame in `traffic.log`.
- `count: 0` means the record type must not appear; `expect_no_other` lists severities that must not appear except as expected.
- `written`, `prev` and `hash` are never compared directly; every test that writes a session file also runs `verify_chain` over it.
- Golden files (`expected/*.jsonl`) are used only for format tests, compared after removing `written`, `prev` and `hash`.

**Injection points** (the only ways a test reaches inside):
- Time: `FakeClock` (`advance`, `jump`), passed to `platform` and `clock`.
- Faults: the `DesktopPlatform` fault plan, using the kinds in the Kind column of `docs/errors.md`; socket and storage errors reach the modules through `platform.fault(op)` (DC-5). Kinds the plan does not deliver are injected by traffic, the harness or test setup.
- Commands: the `cmdserver` socket, or `j1939cmd` at level 3.

**Who owns what:** test-script writers own `tests/fixtures/`, the fixture manifests, `tools/fixtures/` (including `scenario.py`, which writes each fixture folder and its findings ground-truth file, `docs/findings-data/scenarios/<scenario>.json`, from one description), `tests/harness/`, `tests/component/` (level 2, including its fixture runner), `tests/replay/` (level 3), the `bench/` procedures and `bench/checklists.md`, and `tools/findings/`; developers own `src/`, the unit tests and the contract tests (`tests/contract/`). Either side changes the other's area only through a DC entry (DC-4).

**Contract tests:** mypy checks each implementation against its `Protocol` (for example `platform/interface.py`), and one test per module imports only the public names in section 4, so a hidden dependency fails CI.

**Naming:** every test name starts with the requirement ID it verifies (`test_DET_4_copied_name_raises_conflict`); tests of project tooling start with the DC ID that defines the tool (`test_DC_2_...`, DC-6). A fixture's `requirements` list ties it to the verification matrix.

## 6. Contract freeze by build step

| Build step | Contracts frozen before it starts |
|---|---|
| 1. Thin slice | `types`, `platform`, `capture`, `decode`, `eventlog` (append only), `clock` — **frozen 2026-11-13** |
| 2. Sessions and chain | `session`, `eventlog`, `store`, `verify_chain`, `config` — **frozen 2026-11-13** |
| 2a. Beacon go/no-go | none (no code) |
| 3. Transmit | `transmit`, `address`, `requests` — **frozen 2026-11-13** |
| 4. Detection | `detect`, `monitor` — **frozen 2026-11-14** |
| 5. Identification | `identify` |
| 6. Training and inventory | `inventory`, `rawcap`, `retention` |
| 7. Laptop tool | `cmdserver`, `j1939cmd`, `j1939ctl`, `admin`, `status` |
| 8. Beacon | `platform` (Beacon implementation) |
| 9. Documentation | none |

Freezing is a pull request that marks the step's contracts "frozen for step N" in this file, approved by Vaughan Lynn or Elijah Umaru. Step 1's freeze also requires the interface code to be merged first: `types.py`, `platform/interface.py`, `FakeClock` and `DesktopPlatform`. A frozen contract changes only through an accepted entry in `docs/design-changes.md`, which raises its version.
