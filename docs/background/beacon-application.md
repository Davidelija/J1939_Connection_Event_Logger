# Applying the DG Beacon to the J1939 Connected-Devices Logger

Nov 2, 2026 · @Vaughan

> **Background as of Nov 7, 2026.** Where this document differs from `docs/requirements.md`, the requirements win (for example, a known NAME at a new, uncontested address is an `address_change`, not a conflict: DET-4).

## Summary

The two DG Beacons the team already has can cover the logger's whole hardware stack, so the only new hardware needed is a purpose-built short tap cable and possibly a status light. One Beacon is the logger; the other is a bench test instrument.

- **Beacon 1, the logger:** taps the J1939 bus through the short tap, captures all traffic, claims its own address, sends a small set of scheduled requests, runs the detection code and stores the log on its microSD card.
- **Beacon 2, the test instrument (bench only):** independently records the bus to prove the logger sends only allowed messages, and acts as a controlled stand-in for an external device.
- **Software:** Linux and SocketCAN carry the frames. The logger's own code captures them (Python's socket module), handles J1939 (address claiming, transport protocol, decoding) and builds the baseline, connection detection, identification and logging on top.
- **Scope reminder:** J1939 on CAN only, on a single network at the 9-pin port; message-based detection is the primary goal, timing and cadence and below-message methods are out of scope, and ISO 15765 is future research.
- **Before committing:** 15 Beacon capabilities the documentation does not confirm need checking on the units (see Open checks on the Beacon).
- **Fleet approval:** a one-page description of exactly what the logger transmits (its address claim, the allow-listed requests and the required protocol responses) supports approval by fleets and answers OEM or ELD questions.

**Prototype platform.** The DG Beacon is the prototype platform because the team already has two, they are rated for vehicle use (6–32 VDC, −40 to +85 °C), and they run Linux with multiple CAN channels. It is a development and test instrument, not an installation device. Its size, its roughly 1.6 A draw, and mounting it at the diagnostic port make it unsuitable for permanent installation in a fleet vehicle. The logger software is written for Linux and SocketCAN so it can move to a smaller, low-power in-vehicle logger for deployment.

## Hardware stack

From the truck's diagnostic connector up to the stored log, the Beacon covers every layer except the tap cable. Beacon figures are from DG's flyer and user manual.

| Layer | Role | Provided by | Notes |
| --- | --- | --- | --- |
| 1. Vehicle connector | 9-pin Deutsch diagnostic port (J1939-13): ground (A), battery (B), CAN-H (C), CAN-L (D) | The truck | Black (Type I) and green (Type II) connectors can run 250 or 500 kbit/s; the logger detects the rate on the bus. Volvo and Mack trucks with their own engines use a 16-pin connector, and some 2016+ trucks carry powertrain traffic on a separate network: the prototype covers a single J1939 network at the 9-pin port and records the connector and network each session |
| 2. Pass-through tap | Y-splitter: truck side, a female port so the ELD or tool still plugs in, and a short leg to the logger | **New: purpose-built short tap (9-pin splitter with a short leg straight to the Beacon's CAN channel)** | Target under 0.5 m of added stub, including the logger cable (an engineering target, not a standard value). J1939-11 is reported to allow 1 m per stub and 3 m of stubs in total, with tighter limits at 500 kbit/s (figures from a secondary source, unverified until checked against J1939-14 and J1939-15). The budget must include the vehicle's connector stub and any tool cable plugged into the pass-through port. Check for an ELD Y-cable already installed. Installation verifies that bus error counts do not rise with the logger connected. Add no terminator |
| 3. Power | Feeds the logger from pin B | Beacon (6 to 32 VDC input) | Works on 12 V and 24 V trucks. Typical draw is 1.6 A at 12 V. Must sleep at key-off and wake on CAN activity (support unconfirmed), and resume cleanly after a cranking brownout (tested on the bench supply) |
| 4. CAN interface | Transceiver and controller: voltage to bits to frames | Beacon (six high-speed CAN/CAN FD channels; per-channel bit rate, termination and error reporting) | Termination must be **off** on the tap channel. Starts each session listen-only to confirm 250 or 500 kbit/s, then switches to normal mode so the logger can transmit. On bus-off, or error-passive from its own transmit errors, stays listen-only for the rest of the session |
| 5. Compute | Runs Linux, SocketCAN and the detection code | Beacon (embedded Linux, 1 GHz processor; custom stand-alone applications supported) | Whether the channels appear as SocketCAN interfaces, and whether the kernel includes J1939 support, is unconfirmed |
| 6. Storage | Event log and raw-frame captures | Beacon (512 MB NAND flash, microSD up to 64 GB) | Append-only writes synced frequently and a read-only root filesystem protect against sudden power loss. When the card fills, the oldest raw captures are dropped first; event records are kept, with 500 MB reserved for them. If the card fails, the logger shows a fault |
| 7. Clock | Timestamps for the log | Unknown | No battery-backed real-time clock is documented; add a module if absent. Vehicle Time/Date is recorded alongside |
| 8. Retrieval | Getting the log off the logger | Beacon (USB, 100 Mb Ethernet, Wi-Fi) | USB or Ethernet keeps the logger off wireless networks. Wi-Fi and Bluetooth are turned off at the driver level, and only SSH is open on the wired port. The maintenance laptop retrieves logs and produces the summary report |
| 9. Enclosure | Housing for vehicle use | Beacon (rated −40 to +85 °C) | Already vehicle-rated. Mount it rather than hanging it off the port, and label it so technicians don't remove it |
| 10. Status light | Shows the logger's state to anyone at the truck or bench | Beacon LEDs, if software-controllable; otherwise a small external indicator | Needed for bench testing and so a technician who finds the box can see it is working; if no lights are possible, the same states go into a status file read at retrieval |

## Software stack

The lower three layers are configuration and existing libraries; layers 4 to 9 are the project's own code and its research contribution.

| Layer | What it does | Off-the-shelf or built | Example |
| --- | --- | --- | --- |
| 1. Interface setup | Starts listen-only, confirms 250 or 500 kbit/s from clean received frames, then brings the channel up in normal mode; termination off. On bus-off, stays listen-only for the session | Configuration | `ip link set can0 up type can bitrate 250000` |
| 2. Frame capture | Receives every frame with a timestamp | Off-the-shelf: SocketCAN, Python's socket module (python-can optional), can-utils (`candump`) | Raw CAN socket receiving every frame on the bus, with kernel timestamps and a large receive buffer |
| 3. J1939 decoding | Splits each ID into priority, PGN, source and destination; reassembles multi-packet transfers; decodes address claims, requests and DM messages; drops the logger's own transmissions and replies addressed to it | Built on raw CAN sockets: the logger's own J1939 code splits IDs, reassembles transfers and decodes the PGNs of interest (kernel J1939 optional later) | Frame `0x18EA00F9`, data `EC FE 00`: a service tool at address 249 requesting the VIN from the engine |
| 4. Address management and requests | Claims from 247 downward, skipping baseline and reserved addresses; waits 250 ms after any claim; one retry, then "cannot claim"; answers address-claim requests and NACKs others. Schedules the address-claim sweep (every 10 minutes), Time/Date and VIN at every session start, VIN again at training, and identification requests (to unrecognized addresses, and to every device during training), each with a 1.25 s timeout and one retry | Built: address claiming, request scheduling and the transmit queue in the logger's own code | Global Request for Address Claim sent 250 ms after the logger claims address 247 |
| 5. Known-good training | Records known-good NAMEs, addresses and PGNs; started manually with only approved devices, across key-on, engine running and driving; confirmed by a person from the maintenance laptop; the inventory is versioned and tied to the VIN | Built | Devices approved later are added without full retraining |
| 6. Connection detection | Per-connection state machine keyed by NAME (by source address for a device that never claims): known, candidate, connected, disconnected; separates a disconnect from key-off; logs claim conflicts and changes between sweeps; ends a connection after 60 s of silence, with the last frame as its end time | Built | New claim at address 249 during steady state opens a connection |
| 7. Session evidence | Collects NAME fields, each distinct PGN sent with first-seen, last-seen and count, the first 100 requests in order, ECUs contacted, DM types, proprietary PGNs and identification replies; flags control PGNs (TSC1, TC1, XBR, Commanded Address, Reset, DM11 clear codes) at first occurrence with a running count; flags a known address sending a PGN not seen from it in training | Built | Message-based methods (primary goal) |
| 8. Identification | Compares session evidence against a library of characterized devices; returns category, best match, confidence and identification source; separates vehicle ECUs not in baseline and trailer devices from external devices; decodes make from the manufacturer code list in the device library (shipped empty; the user loads a list they are licensed to use) | Built | Rules first, then a similarity score on requested-PGN sets. Cadence features are out of scope |
| 9. Event log | One record per connection with start, end, severity, logger time in UTC and elapsed time; a session header (wake or power-on to key-off) with software, config and inventory versions, VIN, bit rate, connector and network, wake and ready times, session counter, unclean-shutdown flag and vehicle Time/Date; one file per session, rolled over at 24 h with a continuation record; records hash-chained within and across sessions, with training and approval actions recorded in the session file; settings in one versioned config file and the known-good inventory in its own versioned file; raw frames from 10 s before to 60 s after each new connection | Built, on standard formats | JSON lines, one record per line; raw frames in `candump` log format |

Development can happen off the truck: record rig traffic once with `candump`, then replay it onto a virtual CAN interface (`vcan0`) with `canplayer` to build and test layers 3 to 9 at a desk.

## Roles of the two Beacons

Using a separate unit as the test instrument gives independent evidence: a fault in the logger's own setup cannot hide its own transmissions.

|  | Beacon 1: logger | Beacon 2: test instrument |
| --- | --- | --- |
| Where | Bench rig, later a truck | Bench rig only |
| Connection | One channel on the short tap, listen-only at start then normal mode, termination off | One channel on the same bus |
| Job | Runs the full software stack and writes the event log | **Witness:** records all bus traffic while the logger runs. **Device stand-in:** sends address claims, VIN and engine-hours requests, and DM reads to mimic an ELD or code reader; contests the logger's address; sends flagged control PGNs (bench only) |
| Evidence it produces | Detection and identification results | Proof the logger sends only allowed messages (its claim, scheduled requests, required responses) at the allowed rates; repeatable test cases for detection, conflicts and flagged control PGNs |

**Bench setup:**

1. Rig bus with its ECUs, terminated at both ends.
2. Short tap at the diagnostic connector, with Beacon 1 on the tap leg.
3. Beacon 2 on the same bus as witness, or as the stand-in device in the splitter's pass-through port.
4. Known-good ELDs and diagnostic tools plugged into the pass-through port to build the fingerprint library.
5. Bench power supply in place of a truck battery.

## Status indication

The logger shows its state on a status light so a tester or technician can tell at a glance whether it is recording. Each state is also written to the log. The prototype uses one light with three patterns: steady (recording, all good), slow blink (needs attention: new device, needs training, training running or card nearly full) and fast blink (fault); it is off while starting and detecting the bit rate. The table lists the underlying states, which `status` shows in full. When conditions overlap, fast blink wins over slow blink and slow blink over steady; a VIN mismatch, transmission turned off and a restart loop (NP-19) show fast blink. The label on the unit carries a legend of these states and a do-not-unplug notice with a contact.

| State | Meaning | Light |
| --- | --- | --- |
| Starting | Booting or waking; not yet recording | Off |
| Detecting bit rate | Listen-only, confirming 250 or 500 kbit/s | Off |
| Recording | Normal operation | Steady |
| Training | Training mode active | Slow blink |
| Needs training | Untrained mode: no confirmed inventory yet | Slow blink |
| New device | An unreviewed high-severity event | Slow blink |
| Card nearly full | Card use above the warning level (notice fault) | Slow blink |
| Fault | Bus-off, transmit turned off, restart loop, storage error, card full, clock invalid or VIN mismatch | Fast blink; cause written to the log |

## Training and device approval

Training and approvals are done from an authenticated maintenance laptop, because anyone who can trigger them can make their own device known-good.

1. **Connect.** A maintenance laptop connects to the logger by USB or Ethernet and runs `j1939ctl`, a command-line tool that connects over SSH with the operator's key.
2. **Start training.** The operator connects only approved devices and runs `train start`. The status light shows the training state. Training runs across key-on with engine off, engine running and driving (plus PTO where fitted), and ends automatically after a set time if not finished.
3. **Review and confirm.** The operator runs `train finish`. The tool shows the coverage summary and the proposed inventory by entry ID (NAME, address, make, category) and asks whether to apply it. Only a confirmed inventory is applied.
4. **Approve a device later.** The operator runs `approve` with the event ID of a logged connection. The logger adds its NAME to the known-good list without full retraining. Devices, vehicle ECUs and PGNs can also be removed (remove) with a reason; removals apply from the next session. Commands act on stable event and entry IDs and show the change before asking for confirmation.
5. **Record.** The logger versions the known-good list, records its version in each session header, and logs every training start, finish, approval and rejection at notice severity, with operator and time. The inventory is tied to the vehicle's VIN and exported as a machine-readable file.

**Training procedure**

The 2-hour limit is a timeout, not a target; training ends at `train finish`. The aim is to make every ECU show the messages it normally sends.

| Step | Condition | Why |
| --- | --- | --- |
| 1 | Only approved devices connected (for example the fleet ELD); no scan tools | Anything connected becomes known-good |
| 2 | Key on, engine off, 2–3 minutes | Some ECUs only claim and talk at key-on |
| 3 | Crank and start; idle 5 minutes | Start-up claims and engine-running messages |
| 4 | A/C or HVAC, lights, PTO if fitted, engine brake at idle | Body and accessory ECUs |
| 5 | Drive 20–30 minutes: all gears, cruise control, engine brake or retarder, hard braking to trigger ABS only on a closed course or yard | Transmission, brakes, cruise and retarder messages |
| 6 | Key off for 1 minute, then key on again | Session boundary and wake-up claims |
| 7 | `train finish`, review the coverage summary and inventory, then answer y to apply it | A person approves the result |

The coverage summary shows which conditions were seen (engine off, idle, driving, PTO), detected from engine speed and vehicle speed on the bus, with PTO from Power Takeoff Information 1 (PTO1, PGN 65264; engaged when Power Takeoff Speed, SPN 186, is above zero) when sent and otherwise declared by the operator, and the PGNs recorded per ECU in each. Conditions that are hard to produce on demand, such as a particulate filter regeneration, active fault codes or a low-DEF warning, show up later as new PGNs from a known device and are approved one at a time (`approve`).

## Log review

At each retrieval the maintenance laptop produces a summary report, so events are reviewed on a routine rather than left unread. The retrieval schedule and the reviewer are to be agreed with ORNL.

- **Summary contents:** five sections in order: events to review; new devices with make and type; inventory and config changes since the last retrieval, with operator and reason; sessions and gaps, including unclean shutdowns, with versions; and the chain check result with the latest chain hash. Repeated events are grouped by device, and an events.csv file with one row per event is written alongside.
- **On-truck signal:** the status light keeps its slow blink until each high-severity event is reviewed and cleared from the maintenance laptop. Clearing is logged with operator and time.
- **Logger removal:** a session that did not end cleanly is flagged at the next start-up and shows in the summary as a gap.

## Log format

The logger keeps one event file per session plus a few supporting files on the microSD card. The event file is JSON lines: one JSON record per line, written append-only and synced frequently. Example files for one session accompany this doc (session 142).

**Files and layout**

| File | Contents | Written |
| --- | --- | --- |
| `sessions/s000142_20261106T140211Z.jsonl` | Event records for one session, from wake (or power-on) to key-off; session counter and UTC start in the name. A session longer than 24 h rolls over to a new part (`…_p2.jsonl`) | Append-only during the session |
| `raw/s000142_c2_e1.log` | Raw CAN frames in `candump` log format, 10 s before to 60 s after each new connection and each control-flag event; named by session, connection and event number (the example files are abridged) | Once per new connection or control flag; oldest dropped first when the card fills |
| `inventory/inv-v2.json` | Known-good inventory, one version per file, tied to the VIN | At each confirmed training or approval |
| `config/cfg-v3.json` | All settings, one version per file | When settings change |
| `status.json` | Current state for the status light and the maintenance laptop; not part of the hash chain | Overwritten in place |
| `state.json` (internal flash, not the card) | Logger ID, last session number and last hash, so session numbers continue on a replacement card (LOG-5); not part of the hash chain | Atomically at each session start and after each session part |
| `library/lib-v1.json` | Device library: characterized device types (matched on NAME function codes and typical requested and sent PGNs, with source address only as a hint) and the manufacturer code list, one version per file | Copied with the software over SSH (library push deferred); version recorded in session\_start |
| `diag/logger.log` | Diagnostic log: errors, stack traces and restart causes; not hash-chained and not evidence; size-capped and rotated (5 × 10 MB) | As events occur; copied at retrieval |
| `fallback/` | Event records written to the Beacon's internal flash when the card fails, capped at 100 MB; same hash chain | Deferred (LOG-22 fallback); not written by the prototype |

**Fields on every event record**

| Field | Meaning |
| --- | --- |
| `rec` | Record number within the session file, starting at 1 |
| `type` | Record type (table below) |
| `sev` | Severity: `info`, `notice` or `high` |
| `utc` | Time of the event (for a frame, its receive timestamp): logger clock in UTC, ISO 8601 with milliseconds. Every record also carries `written`, the time it was written, in the same format |
| `veh_time` | Vehicle Time/Date (PGN 65254) at that moment, or null before the first reply; whole seconds (J1939 Time/Date resolution is 0.25 s, and the fraction is dropped), the one exception to the millisecond rule |
| `prev` | Hash of the previous record; the first record of a session carries the last hash of the previous session (or part), or after a power loss the hash of its last complete record; an incomplete last line is never rewritten and the verifier reports it as truncated |
| `hash` | SHA-256, as 64 lowercase hex characters, of the UTF-8 bytes of `prev` followed by this record without its `hash` field. The record is serialized as compact JSON (no spaces, separators `,` and `:`), keys in the order written, non-ASCII characters as-is, numbers exactly as written, `hash` always the last key; the verifier removes `hash` and re-serializes the same way. The first record on a new logger uses 64 zeros as `prev` |
| `clock_valid` | Whether the real-time clock was valid when the record was written |
| `clock_source` | Where utc came from: rtc, vehicle (set from Time/Date) or elapsed (time since wake, before any valid time) |

Records tied to a connection also carry `conn` (connection number in the session) and `sa`. Events are referred to by event ID, session and record number (for example 142-4); all times except `veh_time` are ISO 8601 UTC with milliseconds. Records from the maintenance laptop carry `operator`.

**Record types**

| Type | Written when | Severity | Main fields |
| --- | --- | --- | --- |
| `session_start` | Logger ready after wake | info | format version, session, part, software, config, inventory and device library versions, VIN, wake cause, ready time, bit rate and how it was confirmed, receive buffer size read back, connector, network, previous session and how it ended (clean, power loss, software restart, watchdog restart or software update), its cause from the diagnostic log and the bytes cut off after a power loss, logger address and NAME, claim result, new card (first session on a replacement card, LOG-5), whether the restart guard disabled transmit (NP-19), untrained flag, installed operator key fingerprints, VIN status (match, mismatch or unavailable), clock source |
| `time_sync` | First vehicle Time/Date reply | info | source SA, offset from logger clock |
| `sweep` | First sweep of the session, and any sweep that finds a change | info, or notice on a change | NAMEs seen, how many are in the inventory (the logger is listed separately, never in the inventory), NAMEs added or missing |
| `connection_start` | New NAME or new SA, including a device that never claims, and each appearance of an approved external device (severity: high for an unrecognized external device or a vehicle ECU not in baseline, notice for a trailer device, info for an approved external device) | high, notice or info by category | SA, NAME and decoded fields (an approved external device gets the short form: NAME and entry ID, no decoded fields), trigger, in inventory or not, category and the classification rule applied, raw capture file |
| `identification` | Identity requests complete for a connection | notice | each request with reply, NACK or no reply; make; model (null when unknown); make\_source (self-reported, manufacturer code, library or none); type guess; confidence; identification source |
| `control_flag` | First occurrence of a control PGN from a connection | high | PGN and name, target SA, how it was sent, count, raw capture file |
| `address_conflict` | Two NAMEs claim the same address, the logger loses its claim, or the same NAME is active at two addresses (cause "same NAME at two addresses") | notice, or high if a known ECU loses its address or for the same NAME at two addresses | SA (both SAs for the same NAME), both NAMEs, cause, winner, logger action |
| `address_change` | A known NAME claims a new address that no other NAME contests | info, or notice if the address normally belongs to another known ECU | NAME, entry ID, old and new SA, and `conn` when the NAME has an open connection |
| `connection_end` | Silence for detection.silence\_end\_s (60 s) while the bus is active, key-off, or another end reason (see Connection end reason); the end time is the last frame (same severity as its `connection_start`) | high, notice or info by category | start, last frame, end reason, duration; PGNs sent with first-seen, last-seen and count; first 100 requests in order; requests dropped; ECUs contacted; DM types; extended transfers (ETP: sender, destination, PGN, bytes, completed or aborted, memory-transfer flag); control flags; proprietary PGNs; new PGNs from a known SA; final identification (`final_identification`, same fields as `identification`), only when the type, make or model changed since the `identification` record (IDN-4). For approved external devices: start, end, duration, end reason and any new PGNs sent or requested only |
| `known_device_new_pgn` | A known device sends, or an approved external device requests, a PGN outside its trained and approved sets | notice | SA, NAME, PGN, sent or requested, count |
| `operator_login`, `operator_logout` | Maintenance laptop connects or disconnects | notice, info | operator, connection type, laptop tool version |
| `training_start`, `training_finish` | Training started or finished from the laptop | notice | operator, states covered, inventory proposed, coverage summary (conditions seen and PGNs per ECU in each) |
| `approval`, `rejection` | Operator confirms or rejects an inventory, or approves a logged device, a new PGN or a moved address | notice | operator, kind (inventory, device, PGN sent, PGN requested or address), PGN and whether a control-PGN warning was shown, entries affected, new inventory version, reason, events cleared |
| `retrieval` | Logs copied to the laptop | info | sessions and raw files copied, chain check result, last hash |
| `review_clear` | Operator clears reviewed high-severity events | notice | records cleared, disposition, required reason (for example a repair-order number), whether the device was approved, light pattern |
| `fault` | Bus-off, transmit turned off (error-passive, unexpected error, allow-list or rate-cap breach), storage error, card full, card nearly full (notice), start-up self-check failure, invalid clock, no bit rate confirmed within 60 s, or a restart loop (transmit disabled, NP-19); vehicle time and real-time clock more than 5 minutes apart (notice severity) | high (notice where noted) | cause, logger action |
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

**Severity rules**

- **High:** a new external-device connection or vehicle ECU not in baseline, and its end record, a control PGN, a known ECU losing its address, a VIN mismatch, a detection-weakening config change, a logger fault other than a clock disagreement. In untrained mode every event is capped at notice, except the VIN mismatch itself. High events set the status light to slow blink (fast blink for faults) until cleared from the maintenance laptop.
- **Notice:** identification results, a trailer device (NAME says trailer and it only broadcasts), sweep changes, other address conflicts, a new PGN sent by a known address or requested by an approved external device, a clock disagreement, and every operator action, including config changes and rejections.
- **Info:** session start and end, time sync, routine sweeps and retrievals, and connections of approved external devices.

**Supporting file contents**

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

## Platform requirements on the Beacon

How the Beacon meets the hardware-neutral platform requirements (PLT-1 to PLT-8 in the requirements). The Beacon-specific code lives in `platform/beacon.py`. The Beacon also meets HW-3 (6 to 32 VDC) and HW-4 (−40 to +85 °C) by its rating.

| Requirement | On the Beacon | Status |
| --- | --- | --- |
| PLT-1 Linux, SocketCAN, can-utils | Embedded Linux; whether channels appear as SocketCAN interfaces is unconfirmed | Open check |
| PLT-2 Listen-only, error reporting, timestamps and drop count, 250 and 500 kbit/s, termination off | Per-channel bit rate, termination and error reporting are documented; listen-only is unconfirmed | Open check |
| PLT-3 Real-time clock with backup battery | None documented; add a USB or I2C module | Open check |
| PLT-4 Wake on CAN, sleep current | Running draw about 1.6 A at 12 V | Deferred (future research, X39) |
| PLT-5 Industrial-grade removable storage | microSD up to 64 GB (the HW-9 starting capacity); fit an industrial-grade card | Agreed |
| PLT-6 Python, install without internet | Python version and pip support unconfirmed | Open check |
| PLT-7 CPU and RAM | 1 GHz processor; read RAM on the unit (`free -m`); load figures from SC-9 | Measured in step 8 |
| PLT-8 systemd watchdog and an indicator | systemd version and controllable LEDs unconfirmed | Open check |

## Hardening on the Beacon (STS-20)

The Beacon-specific install steps for STS-20, each confirmed on the install checklist:

1. Change or remove DG's default accounts and passwords.
2. Turn off root SSH login and SSH password login; install operator keys with `release/keys.sh`.
3. Unload the Wi-Fi and Bluetooth drivers and stop them loading at boot.
4. Stop and disable DG services the logger does not use (listed during the open check).
5. Allow only SSH on the wired Ethernet port.
6. Mount the root filesystem read-only.

Any step that cannot be done on the Beacon is recorded as a known limitation.

## Open checks on the Beacon

SocketCAN transmit is the check that decides whether the Beacon can be the logger without extra software. Kernel J1939 support is now optional: the logger uses raw CAN sockets with its own J1939 handling. None of the 15 is confirmed by DG's documentation. They are run on the unit in build step 2a, before any transmit code, as a go/no-go (decisions X18, X41); a SocketCAN or listen-only failure switches the hardware tier to the backup platform (X21, porting guide).

| Check | Why it matters | How to verify | If it fails |
| --- | --- | --- | --- |
| Kernel J1939 support | Only the optional kernel J1939 sockets depend on it; the logger does its own address claiming and transfer handshakes | uname -r (5.4 or later), then try loading the can-j1939 module | No impact: raw CAN sockets with the logger's own J1939 handling are the default |
| SocketCAN interfaces and transmit | The software stack assumes channels appear as `can0`, `can1`, etc. | `ip link show` on the Beacon | Switch to the backup platform (X21); the vcan fallback (X12) applies if that also fails |
| Real-time clock | Log timestamps must survive power loss | Power-cycle with no network and compare the clock | Add a USB or I2C RTC module. Vehicle Time/Date is recorded alongside in any case |
| Sleep and wake on CAN | The logger must sleep at key-off (a running Beacon draws about 1.6 A, roughly 38 Ah a day) and wake on CAN activity | Measure draw with a bench supply; look for a sleep mode with wake on CAN | Sleep is future research (X39): the prototype records wake and ready time only and stays powered on the bench |
| Boot and wake-to-ready time | Traffic sent before the logger is ready is lost | Time from power-on, and from wake, to the first received frame | Record ready time in each session; the address-claim sweep recovers NAMEs of devices that claimed during the gap |
| Controllable status LEDs | Status indication depends on lights the logger software can drive | Look for LED entries under /sys/class/leds on the Beacon, or ask DG | Add a small USB indicator, or write states to a status file read at retrieval |
| Listen-only mode for start-up | The bit rate must be confirmed without transmitting, or a wrong rate could disturb the bus | ip -details link show lists the controller's supported modes | Switch to the backup platform (X21); the vcan fallback (X12) applies if that also fails |
| Default accounts, services and radios | Hardening (STS-20) needs every default account, unused DG service and radio to be removable or switchable off | List accounts, listening ports, running services and loaded radio drivers | Ask DG how to disable them; record any that cannot be turned off as a known limitation |
| cryptography package | Seals (LOG-24) and signed updates (STS-22) use Ed25519 | pip install on the Beacon, then sign and verify a test message | Deferred; only needed when LOG-24 or STS-22 is built |
| DG service owning the CAN channels | DG's server may hold the CAN hardware and serve it to its own clients | Stop DG services and try `candump can0`; check which process has the device open | Switch to the backup platform (X21) |
| Error reporting and bus-off restart | NP-3 must tell its own transmit errors from receive errors and stay off after bus-off | `ip link set can0 type can berr-reporting on`; check the TX/RX error-passive flags in error frames; confirm `restart-ms 0` is honoured | Switch to the backup platform (X21) |
| Termination control | HW-2 needs termination off on the tap channel | `ip link set can0 type can termination 0` | Termination off in the tap wiring; record the gap |
| Receive buffer and privileges | LOG-15's buffer is capped by `net.core.rmem_max` | Read and raise `rmem_max`; check for root or CAP\_NET\_ADMIN | Smaller buffer; watch drops in SC-9 |
| CPU, RAM, storage and card filesystem | Wheelhouse build target, the PLT-7 baseline and the ext4 card (X26) | `uname -m`, `nproc`, `free -m`, `df -h`, `lsblk -f` | Reformat the card as ext4; ship a matching runtime |
| USB-B port as USB-Ethernet | STS-5 assumes the laptop can connect over USB-Ethernet | Connect a laptop over USB-B and look for a network adapter | Use the Ethernet port |
| Listening services | Hardening (STS-20): FTP and the web server must be off | `ss -tlnp` | Ask DG; record any that cannot be turned off as a known limitation |

## Sources

- DG Technologies, [Beacon flyer](https://www.dgtech.com/wp-content/uploads/2022/11/Beacon-flyer2022.pdf), 2022 (channels, storage, power, connectivity, temperature range).
- DG Technologies, [Beacon User Manual](https://www.dgtech.com/wp-content/uploads/2018/01/Beacon_User_Manual.pdf) (embedded Linux, custom applications, channel settings, date and time handling).
- Linux kernel, [J1939 documentation (v6.11)](https://www.kernel.org/doc/html/v6.11/networking/j1939.html) (address-claim tracking, promiscuous mode).
- Stub-length limits from an [ASE T6 study guide](https://open-exam-prep.com/study-guides/ase-t6/data-networks-multiplexing/j1939-can-bus-specifications); connector types and bit rates from [Diesel Laptops](https://www.diesellaptops.com/blogs/news/the-new-green-9-pin-j1939-connectors-explained) and [Volvo Trucks, OBD changes for 2016](https://volvotrucks.us/volvo-premium-tech-tool/media/fragments/obd-changes-for-2016.pdf). Pinouts and limits should still be checked against J1939-11, J1939-13, J1939-14 and J1939-15.
