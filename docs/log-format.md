# J1939 Event Logger: Log Format

Originally exported from the DG Beacon application doc's Log format section; from Nov 10, 2026 this file is the only copy (decision X19). This is the authoritative schema for every file the logger writes. Worked examples are in `docs/examples/`.

The logger keeps one event file per session plus a few supporting files on the microSD card. The event file is JSON lines: one JSON record per line, written append-only and synced frequently. Example files for one session accompany this doc (session 142).

## Files and layout

| File | Contents | Written |
| --- | --- | --- |
| `sessions/s000142_20261106T140211Z.jsonl` | Event records for one session, from wake (or power-on) to key-off; session counter and UTC start in the name, or `_noclock` in place of the UTC start when no valid time exists at session start (`s000143_noclock.jsonl`, DC-10). A session longer than 24 h rolls over to a new part (`…_p2.jsonl`): the part being closed ends with `session_end` (reason "session roll-over") and the new part starts with a repeated `session_start` with the same session number and `part` raised by one; the chain continues across parts (DC-10) | Append-only during the session |
| `raw/s000142_c2_e1.log` | Raw CAN frames in `candump` log format, 10 s before to 60 s after each new connection and each control-flag event; named by session, connection and event number (the example files are abridged) | Once per new connection or control flag; oldest dropped first when the card fills |
| `inventory/inv-v2.json` | Known-good inventory, one version per file, tied to the VIN | At each confirmed training or approval |
| `config/cfg-v3.json` | All settings, one version per file | When settings change |
| `status.json` | Current state for the status light and the maintenance laptop; not part of the hash chain | Overwritten in place |
| `state.json` (internal flash, not the card) | Logger ID, last session number and last hash, so session numbers continue on a replacement card (LOG-5); not part of the hash chain. Layout (DC-10): `{"format": "state-1", "logger_id": "0x9FFEFFFFFFE00001", "session": 142, "last_hash": "<64 hex>", "unclean_starts": []}`; `logger_id` is the logger NAME (`address.name`); `unclean_starts` lists the UTC times (or null without a valid clock) of recent unclean starts, for the restart guard (NP-19, DC-12) | Atomically at each session start and after each session part |
| `library/lib-v1.json` | Device library: characterized device types (matched on NAME function codes and typical requested and sent PGNs, with source address only as a hint) and the manufacturer code list, one version per file | Copied with the software over SSH (library push deferred); version recorded in session\_start |
| `diag/logger.log` | Diagnostic log: errors, stack traces and restart causes; not hash-chained and not evidence; size-capped and rotated (5 × 10 MB) | As events occur; copied at retrieval |
| `fallback/` | Event records written to the Beacon's internal flash when the card fails, capped at 100 MB; same hash chain | Deferred (LOG-22 fallback); not written by the prototype |

## Fields on every event record

| Field | Meaning |
| --- | --- |
| `rec` | Record number within the session, starting at 1; it keeps counting across the parts of a session, so event IDs stay unique (DC-11) |
| `type` | Record type (table below) |
| `sev` | Severity: `info`, `notice` or `high` |
| `utc` | Time of the event (for a frame, its receive timestamp): logger clock in UTC, ISO 8601 with milliseconds. Every record also carries `written`, the time it was written, in the same format. While `clock_source` is `elapsed` there is no UTC: `utc` and `written` are null and the record carries `elapsed_s` instead (DC-10) |
| `elapsed_s` | Only on records whose `clock_source` is `elapsed`: seconds since wake for the event, to the millisecond (DC-10) |
| `veh_time` | Vehicle Time/Date (PGN 65254) at that moment, or null before the first reply; whole seconds (J1939 Time/Date resolution is 0.25 s, and the fraction is dropped), the one exception to the millisecond rule |
| `prev` | Hash of the previous record; the first record of a session carries the last hash of the previous session (or part), or after a power loss the hash of its last complete record; an incomplete last line is never rewritten and the verifier reports it as truncated |
| `hash` | SHA-256, as 64 lowercase hex characters, of the UTF-8 bytes of `prev` followed by this record without its `hash` field. The record is serialized as compact JSON (no spaces, separators `,` and `:`), keys in the order written, non-ASCII characters as-is, numbers exactly as written, `hash` always the last key; the verifier removes `hash` and re-serializes the same way. The first record on a new logger uses 64 zeros as `prev` |
| `clock_valid` | Whether the real-time clock was valid when the record was written |
| `clock_source` | Where utc came from: rtc, vehicle (set from Time/Date) or elapsed (time since wake, before any valid time) |

Records tied to a connection also carry `conn` (connection number in the session) and `sa`. Events are referred to by event ID, session and record number (for example 142-4); all times except `veh_time` are ISO 8601 UTC with milliseconds. Records from the maintenance laptop carry `operator`.

## Record types

| Type | Written when | Severity | Main fields |
| --- | --- | --- | --- |
| `session_start` | Logger ready after wake | info | format version, session, part, software, config, inventory and device library versions, VIN, wake cause, ready time, bit rate and how it was confirmed, receive buffer size read back, connector, network, previous session and how it ended (clean, power loss, software restart, watchdog restart or software update), its cause from the diagnostic log and the bytes cut off after a power loss, logger address and NAME, claim result, new card (first session on a replacement card, LOG-5), whether the restart guard disabled transmit (NP-19), untrained flag, installed operator key fingerprints, VIN status (match, mismatch or unavailable), clock source |
| `time_sync` | First vehicle Time/Date reply | info | source SA, offset from logger clock |
| `sweep` | First sweep of the session, and any sweep that finds a change | info, or notice on a change | NAMEs seen, how many are in the inventory (the logger is listed separately, never in the inventory), NAMEs added or missing |
| `connection_start` | New NAME or new SA, including a device that never claims, and each appearance of an approved external device (severity: high for an unrecognized external device or a vehicle ECU not in baseline, notice for a trailer device, info for an approved external device) | high, notice or info by category | SA, NAME and decoded fields (an approved external device gets the short form: NAME and entry ID, no decoded fields), trigger, in inventory or not, category and the classification rule applied (a Classification rule value), with any detail in `classification_detail`, raw capture file |
| `identification` | Identity requests complete for a connection | notice | each request with reply, NACK or no reply (`value`: the reply text without its trailing `*`; DC-17); make; model (null when unknown); make\_source (self-reported, manufacturer code, library or none); type guess (null when no library entry scores above 0); confidence; identification source (`id_source`: a list of Identification source values); `profile_match` ("matches <make> <model> profile" for a library-only make or model, else null); `disagreements` (each source's `{source, make, model}` when they differ, else empty); `candidates` (the tied types on a type tie, else null); `category` and `classification_rule`; `reclassified` (the reason, when the category changed, else null) (DC-17) |
| `control_flag` | First occurrence of a control PGN from a connection | high | PGN and name, target SA (null for global), how it was sent (`via`: single frame, transport (BAM), transport (RTS/CTS) or requested; DC-13, DC-14), count, raw capture file (`raw_capture`, null until `rawcap` in step 6 and whenever no capture was written; DC-14) |
| `address_conflict` | Two NAMEs claim the same address, the logger loses its claim, or the same NAME is active at two addresses (cause "same NAME at two addresses") | notice, or high if a known ECU loses its address or for the same NAME at two addresses | SA (both SAs for the same NAME), both NAMEs, cause, winner, logger action |
| `address_change` | A known NAME claims a new address that no other NAME contests | info, or notice if the address normally belongs to another known ECU | NAME, entry ID, old and new SA, and `conn` when the NAME has an open connection |
| `connection_end` | Silence for detection.silence\_end\_s (60 s) while the bus is active, key-off, or another end reason (see Connection end reason); the end time is the last frame (same severity as its `connection_start`) | high, notice or info by category | start, last frame, end reason, duration; PGNs sent with first-seen, last-seen and count (the PGN each message carries: a transfer counts once as its reassembled PGN, never as TP.CM or TP.DT; DC-15); first 100 requests in order (`requests_first_100`, up to `detection.requests_kept` items, each `"<pgn> <name> -> SA <n>"` or `"<pgn> <name> -> global"`, the name left out when the logger has none; DC-14); requests dropped; PGNs dropped after `limits.pgns_per_conn` (`pgns_dropped`, messages not added to the full table; DC-13, DC-14); ECUs contacted (`ecus_contacted`, ascending destinations of destination-specific messages, never the logger; DC-14); DM types; extended transfers (`etp_transfers` items `sender`, `destination`, `pgn`, `bytes`, `result` completed or aborted (still open at the end counts as aborted), `memory_transfer`; DC-14); control flags; proprietary PGNs; new PGNs from a known SA (`new_pgns` items `pgn`, `name`, `direction` sent or requested; DC-14); final identification (`final_identification`, same fields as `identification`), only when the type, make or model changed since the `identification` record (IDN-4). For approved external devices: start, end, duration, end reason and any new PGNs sent or requested only |
| `known_device_new_pgn` | A known device sends, or an approved external device requests, a PGN outside its trained and approved sets | notice | SA, NAME, PGN, sent or requested (`direction`, DC-14), count |
| `operator_login`, `operator_logout` | Maintenance laptop connects or disconnects | notice, info | operator, connection type, laptop tool version |
| `training_start`, `training_finish` | Training started or finished from the laptop | notice | operator, states covered, inventory proposed, coverage summary (conditions seen and PGNs per ECU in each); `timed_out` (true when `training.timeout_min` stopped the observation first; DC-20) |
| `approval`, `rejection` | Operator confirms or rejects an inventory, or approves a logged device, a new PGN or a moved address | notice | operator, kind (inventory, device, PGN sent, PGN requested or address), PGN and whether a control-PGN warning was shown (`pgn`, `control_warning_shown`), entries affected (`entries`), new inventory version (`new_inventory`), reason, events cleared (`events_cleared`: the source event; DC-20) |
| `retrieval` | Logs copied to the laptop | info | sessions and raw files copied, chain check result, last hash |
| `review_clear` | Operator clears reviewed high-severity events | notice | records cleared, disposition, required reason (for example a repair-order number), whether the device was approved, light pattern |
| `fault` | Bus-off, transmit turned off (error-passive, unexpected error, allow-list or rate-cap breach), storage error, card full, card nearly full (notice), start-up self-check failure, invalid clock, no bit rate confirmed within 60 s, or a restart loop (transmit disabled, NP-19); vehicle time and real-time clock more than 5 minutes apart (notice severity) | high (notice where noted) | cause, logger action |
| `vin_check` | The VIN request at session start gets a reply, a NACK or no reply (DC-12) | info | VIN received (or null), `vin_status` (match, mismatch or unavailable), inventory VIN and version, request outcome |
| `vin_mismatch` | VIN received at session start differs from the inventory's VIN | high | VIN received, inventory VIN, inventory version; session switched to untrained mode |
| `config_change` | A new config version is accepted from the maintenance laptop | notice | operator, old and new versions, changed fields, whether it weakens detection (then high severity, needs --confirm); applies from the next session |
| `config_rejected` | A pushed config fails validation or adds to the transmit allow-list | notice | operator, proposed version, reason |
| `operator_add`, `operator_remove` | Deferred, not written by the prototype: an operator key is installed or removed (session\_start lists the key fingerprints instead) | notice | operator added or removed, key fingerprint, operator who made the change |
| `pgn_approval` | Not written: PGN approvals use the approval record with kind PGN sent or PGN requested | notice | operator, NAME, PGN, sent or requested, control-PGN warning shown, reason, source event, new inventory version |
| `library_change`, `library_rejected` | Deferred (IDN-7), not written by the prototype: a device library version is pushed from the laptop and accepted or rejected | notice | operator, old and new versions (or proposed version and reason), entries changed |
| `reset` | Operator runs restart or retrain (move and wipe deferred) | notice | operator, mode, reason, verified retrieval (move and wipe), what was archived or deleted, new VIN and settings (move); a wipe's first following record carries the last hash before it |
| `inventory_remove` | Operator removes a device, vehicle ECU or PGN from the inventory | notice | operator, entry ID, NAME, what was removed (device, PGN sent or PGN requested), reason, training-ECU warning shown, old and new inventory versions; applies from the next session |
| `software_update` | Deferred (STS-15, STS-16), not written by the prototype: operator installs a release (update) or returns to the previous one (rollback) | notice | operator, update or rollback, old and new software versions, package checksum, reason; applies from the next session |
| `chain_start` | Deferred (LOG-21), not written by the prototype: first record on a blank card, before session\_start | notice | reason (new card), logger NAME, software version; prev is 64 zeros, and the laptop links it to the last hash retrieved from that logger |
| `seal` | Deferred (LOG-24), not written by the prototype: session end, every 10 minutes, and within 5 s of every high event | info | trigger (periodic, after high event, session end), chain hash sealed, Ed25519 signature, signing key fingerprint; the key is kept on internal flash, never on the card |
| `flood` | Deferred (DET-19 flood record), not written by the prototype: more than 20 new connections in a minute | high | minute start, connections recorded, connections counted only, NAMEs and SAs seen (first 100) |
| `admin_login` | Deferred (STS-21), not written by the prototype: an admin key opens a shell on the logger | notice | admin, key fingerprint, connection type, login and logout time |
| `session_end` | Key-off and bus silent, or roll-over to a new part | info | reason, connections, counts by severity, frames received, bus errors, bus-off, everything the logger transmitted, sweeps run, card use, frames dropped by the kernel (SO\_RXQ\_OVFL), frames that aren't J1939 by type (11-bit, remote, error) |

## Severity rules

- **High:** a new external-device connection or vehicle ECU not in baseline, and its end record, a control PGN, a known ECU losing its address, a VIN mismatch, a detection-weakening config change, a logger fault other than a clock disagreement. In untrained mode every event is capped at notice, except the VIN mismatch itself. High events set the status light to slow blink (fast blink for faults) until cleared from the maintenance laptop.
- **Notice:** identification results, a trailer device (NAME says trailer and it only broadcasts), sweep changes, other address conflicts, a new PGN sent by a known address or requested by an approved external device, a clock disagreement, and every operator action, including config changes and rejections.
- **Info:** session start and end, time sync, routine sweeps and retrievals, and connections of approved external devices.

## Supporting file contents

- **Inventory:** format, version, VIN, previous version, what changed, operator, source session; for each entry a permanent entry ID (never reused), the raw NAME and decoded fields, make, model, addresses and vehicle states seen, category, self-reported identity, PGNs normally sent (and requests made, for approved external devices), and how and when it was added; PGNs approved later (sent and requested), kept separate from trained PGNs, each with reason and date; and the vehicle configuration (make, model, year, engine, software level) for future fleet profiles.
- **Config:** format, version, operator and change; network address; CAN interface, termination, bit rates, bit-rate check frames and fault time, receive buffer; logger NAME, claim range, reserved addresses, claim wait and retries; request allow-list, VIN request address, sweep interval, timeout and retries; transmit allow-list and rate limits; silence time, requests kept, control PGN list, new-PGN switch; classification wake window and trailer vehicle system; input limits; session-end silence; roll-over time, sync interval, hash method, raw capture window; event reserve and warning level; diagnostic log size; watchdog timeout; restart guard count and window; identification tie margin; clock skew limit; training timeout and states; connector and network. These are exactly the keys in the requirements' configuration table.
- **Device library:** format, version; for each device type its name, optional make and model (null for a generic type), NAME function codes, typical requested PGNs, typical sent PGNs, PGNs it never requests or sends, source-address hints and notes; the manufacturer code list (shipped empty; the user loads a list they are licensed to use). The repo source `data/device_library.json` is installed on the logger as `library/lib-vN.json`; raising the library version means changing the `library` field (`lib-v1` → `lib-v2`); the format stays `lib-1`.
- **Status:** format, time, state, session, bit rate, logger address, unreviewed high events, light pattern, fault, card use and card write totals where reported, card nearly full flag, clock valid and source, untrained flag, files already retrieved (a session retrieved while in progress is marked partial), training coverage while training, config and inventory versions.

**Format history**

The session header and every supporting file carry a `format` field. Any change to a field or record type raises the format version and adds a line here; the verifier and report refuse a format they do not know.

| Format | Change |
| --- | --- |
| log-1 | First session file format (Nov 2026) |
| cfg-1 | First config format (Nov 2026) |
| inv-1 | First inventory format (Nov 2026) |
| lib-1 | First device library format (Nov 2026) |
| status-1 | First status file format (Nov 2026) |
| state-1 | First `state.json` format (Nov 2026, DC-10) |
| log-1 | `elapsed_s` on records without a valid time; `_noclock` file names; parts start with a repeated `session_start` (DC-10). No release had shipped, so the format stays log-1 |
