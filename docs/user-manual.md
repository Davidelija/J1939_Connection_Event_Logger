# J1939 event logger: user manual

Skeleton. Each section is filled in by the build step that delivers its feature (hand-off, Documentation to deliver) and finished in step 9 with real bench output. Each task gives when to do it, the steps, example screen output and what can go wrong.

## 1. Getting started

### What the logger does

The logger sits on a short tap at a heavy truck's 9-pin J1939 diagnostic connector. During training it learns which devices normally sit on the vehicle network. After that it watches every session, from key-on to key-off, for anything new: an ELD, a scan tool or any other device.

**What it records.** For each new device: when it connected and disconnected, its address and NAME, what kind of device it seems to be, what it sent and what it asked for. It also records raw CAN frames from 10 s before to 60 s after each new connection. Records are hash-chained, so a changed or missing record shows up when the logs are checked.

**What it sends.** Only a small, fixed set of frames: its own address claim (always at an address from 128 to 247, and it always gives way in a conflict), and requests for address claims, the vehicle's time and date, the VIN, and the identity of new devices, plus the replies J1939 requires of every node (answering a request for its address claim, refusing other requests addressed to it, and transport-protocol handshakes for replies sent to it). It sends at most 10 frames a second.

**What it never does.** It never sends a command, a clear or a write, and never gives data to other devices. It does not use Wi-Fi or Bluetooth. It never deletes its event logs, not even after retrieval.

**Where the data goes.** Everything is written to the logger's card. A maintenance laptop retrieves the logs over a wired SSH connection, checks the chain and produces a report for review.

**How it decides a device is new.** Each device that claims an address is known by its 64-bit NAME, so a known ECU that moves to another address is still recognized; a device that never claims is known by its address. At the start of a session the logger waits for its first address-claim sweep before deciding about addresses that send without claiming. A connection ends after 60 s of silence from the device while the rest of the bus keeps talking, or at key-off. The connection's end record lists every PGN the device sent, its first 100 requests, the ECUs it addressed, diagnostic activity, extended transfers, control PGNs and proprietary PGNs.

**How it identifies a device.** For each new device the logger asks for its Component ID, Software ID and ECU ID, then combines the answers with the NAME and the PGNs the device requested. It compares the requests against the device library (`library/lib-vN.json` on the card) and records a type guess, a make and model when one is known, and a confidence (high, medium or low). A make or model that comes only from the library is reported as a profile match. A device whose NAME says it is a trailer is logged at notice; if it then sends requests, control PGNs or memory access, it is reclassified as an unrecognized external device and the reason is recorded. If the library file is corrupt, the logger records a high fault and keeps identifying without it.

**How it learns the truck.** During training the logger records every device on the bus, the conditions it is heard in (key-on engine off, idle, driving and PTO, taken from engine speed, vehicle speed and PTO speed, or PTO declared by the operator) and the PGNs each device sends. At train finish it proposes an inventory; nothing is applied until an operator confirms it, and a rejected proposal is discarded. Later an operator can approve a logged device, a new PGN or a moved address, or remove a device or one PGN; each change is saved as a new inventory version and applies from the next session. If the VIN the truck reports differs from the inventory's VIN, the logger records a high VIN mismatch and treats every device as new for the rest of the session. For each new device and each control flag it also saves the raw CAN frames from 10 s before to 60 s after, in `raw/`; when the card runs low it deletes raw captures (retrieved ones first) and never event files.

*(The rest of this chapter is written as each build step lands.)*

- What you need *(below)*
- Running the no-hardware demo *(below)*

### What you need

- **A Windows laptop** with Python 3.9 or later and the Windows OpenSSH client (Settings, Apps, Optional features, OpenSSH Client). Nothing else is installed on the laptop. Until the release bundle exists (steps 8 and 9), run the tool from a copy of the repository: `python -m j1939ctl <command>` with the repository's `src` folder on `PYTHONPATH`. This manual writes it as `j1939ctl <command>`.
- **Your operator key:** an Ed25519 SSH key with a passphrase, one per person. An admin installs its public key on the logger (with `release/keys.sh`, step 8); the logger lists every installed key's fingerprint in each session header, and records the key you used with every change you make.
- **A wired connection:** an Ethernet cable, or a USB-Ethernet adapter, to the logger's wired port.

### Running the no-hardware demo

**When:** to see the logger work before you have hardware, or to check a new copy of the software.

**You need:** a Linux machine or virtual machine with Python 3.9 or later, `sudo` rights (to load the virtual CAN module), and can-utils (`sudo apt-get install can-utils` on Debian or Ubuntu).

**Steps:**

1. Get the repository and change into its folder.
2. Run `bash demo/run_demo.sh`.

The demo brings up a virtual CAN interface (`vcan0`), starts the logger listening only, replays a recorded capture in which a scan tool joins the bus, stops the logger, checks the hash chain and lists the records written. It ends with lines like these (example; the hash and record count differ from run to run; real output will replace this in step 9):

```
chain verifies: 1 files, 4 records, last hash 3f2a…
  rec   1  session_start      info
  rec   2  connection_start   high   sa=249 category=vehicle ECU not in baseline
  rec   3  session_end        info
demo passed: the scan tool's claim gave a chained connection_start
```

(The scan tool shows as "vehicle ECU not in baseline" here because the replay is fast, so it claims within 10 s of the first frame; on a truck it would join later and show as an external device.)

**What can go wrong:**

| Message | What to do |
| --- | --- |
| `modprobe: FATAL: Module vcan not found` | Install the extra kernel modules for your kernel (`sudo apt-get install linux-modules-extra-$(uname -r)`), then run the demo again. |
| `canplayer not found: install can-utils` | `sudo apt-get install can-utils`. |
| `logger did not start` | The logger's own messages are printed above this line; a config error names the key at fault. |
### Connecting the laptop

1. Plug the cable into the logger's wired port and the laptop. The logger runs a DHCP server on that port only, so the laptop gets an address of the form 192.168.250.x by itself.
2. Run `j1939ctl status`. The tool reaches the logger at its fixed address, 192.168.250.1 (`network.address`); give `--host` if your logger was set up with another one.
3. The first time, OpenSSH asks you to accept the logger's host key, and asks for your key's passphrase.

If it cannot connect, the message names the address it tried; check the cable and that the laptop has a 192.168.250.x address (troubleshooting table, "Laptop").

- Installing the logger, including the VIN request address `requests.vin_sa` (default 0, the engine) *(step 8)*

## 2. Everyday use
### The status light and the `status` screen

The logger has one light. When more than one applies, fast blink wins over slow blink, and slow blink over steady.

| Light | Meaning | What to do |
| --- | --- | --- |
| Off | Starting, or finding the bus's bit rate | Wait; if it stays off with the key on, run `status`. |
| Steady | Recording, all good | Nothing. |
| Slow blink | Needs attention: high events to review, needs training, training running, or the card is nearly full | Run `status`; its Next step line says which. |
| Fast blink | A fault: a high fault, a VIN mismatch, transmit turned off, or a restart loop | Run `status`, then the troubleshooting table. |

`j1939ctl status` shows the state and light, VIN, session, the number of events to review, whether training is needed, card use, the logger's clock and its difference from the laptop's, the versions in use, and a **Next step** line. It works when the logger service is down, from the last saved status. (On the Beacon, which LED shows the light is set in step 8.)

### Training a truck

Training teaches the logger which devices belong on this truck.

1. Run `j1939ctl train start`. The light slow-blinks while training runs.
2. Drive through every condition: key on with the engine off, engine idling, driving, and PTO if the truck has one. The logger takes the condition from engine speed, vehicle speed and Power Takeoff Information 1 (PGN 65264, engaged when Power Takeoff Speed is above zero).
3. Run `j1939ctl train status` at any time: it shows the time used and left, the conditions covered and still to cover, and the devices found with how many PGNs each sends.
4. Run `j1939ctl train finish`, adding `--pto` if PTO was used but the truck does not report it. The tool lists the proposed inventory by entry ID (for example E07), with each device's NAME, address, make, category, PGNs sent and requests made, and asks "Apply this inventory? y/N". Only y applies it; it takes effect from the next session.

Training stops by itself after 120 minutes (`training.timeout_min`); the proposal then waits for `train finish`.

- Reviewing new events: run `events`, then `approve` a device you know or `clear` it with the repair-order number; the slow blink stops when every high event is cleared.
### Changing the inventory

- **Add a device or a PGN that turned up later:** `j1939ctl approve <event-id>` (for example `approve 142-37`). It approves the logged device, a new PGN (with a warning line if it is a control PGN) or a moved address, and clears that event.
- **Remove a device, or one PGN of it:** `j1939ctl remove <entry-id>`, or `remove E07 --pgn 61444 --direction sent` (or `requested`). Removing an ECU found in training prints a warning line.
- Each change shows what will change, asks for a reason and asks y/N; it saves a new inventory version that applies from the next session. Old versions are kept. `j1939ctl inventory show` shows the current one; `inventory export --out FILE` writes it as CSV.

- Retrieving logs and running the report: `retrieve`, then `report logs/<VIN>`; the chain check result and the latest chain hash are in section 5.
### Reading the report

`j1939ctl report logs/<VIN>` shows a plain-text report and saves it beside the retrieved folder (which is read-only) as `logs/report-<VIN>-<date and time>.txt`, with the events as `logs/events-<VIN>.csv`. It works offline. Its five sections, in order:

1. **Events to review:** high events not yet cleared, by event ID.
2. **New devices:** each new connection by event ID, with its address, NAME, category, and the type and make identification found (or unknown).
3. **Changes since the last retrieval:** inventory and config changes, each with operator and reason, for the reviewer's sign-off; changes that weaken detection are marked.
4. **Sessions and gaps:** each session with its counter and its software, config and inventory versions, and any gaps between sessions.
5. **Chain check:** the result of checking the hash chain, and the latest chain hash.

- Changing a setting: edit a copy of the config with a new version number, then `config push <file>`; it applies from the next session.

## 3. Less common tasks
- Restart or retrain: `restart --reason ...` restarts the software; `retrain --reason ...` archives the inventory so the truck can be trained again.
- Moving the logger to another truck by hand *(step 8)*
- Replacing the card or removing the logger; the card is ext4, so card-swap retrieval needs a Linux machine or VM; the new card starts a new chain, which the chain check reports as a declared break; session numbers carry on from the logger's internal flash (if that isn't writable, `install.sh` asks for the next session number) *(step 8)*

## 4. For analysts

### The files on the card

The card is formatted ext4. On it:

| Folder or file | What it holds |
| --- | --- |
| `sessions/` | One event file per session: `s000142_20261106T140211Z.jsonl` (session number and UTC start). A session longer than 24 hours continues in parts (`…_p2.jsonl`). A session started with no valid clock is named `…_noclock.jsonl`. |
| `raw/` | Raw CAN frames around each new connection, in candump format. |
| `inventory/`, `config/`, `library/` | One file per version of the inventory, config and device library (`inv-v2.json`, `cfg-v3.json`, `lib-v1.json`). Old versions are kept. |
| `status.json` | The logger's current state. |
| `diag/logger.log` | The diagnostic log: errors and restart causes. It is not evidence and not hash-chained. |

The logger's internal flash (not the card) holds `state.json`: the last session number and last hash, so numbering continues when the card is replaced.

**Session file layout.** Each line is one record in JSON. The first record of a session (and of each part) is `session_start`, the header: software, config, inventory and library versions, VIN, bit rate, how the previous session ended, and the logger's identity. The last is `session_end`: why it ended and the counts for the session. Between them come the events (`connection_start`, `time_sync`, `fault` and others). Every record carries its record number `rec` (which keeps counting across parts), its type, severity, time (`utc`), the time it was written, and the hash chain fields `prev` and `hash`. An event is named by session and record number, for example 142-5. The full schema is in `docs/log-format.md`.

### The chain check

Every record carries the hash of the record before it, so a changed, deleted or inserted record shows up. To check a set of session files (retrieved, or copied from a card):

```
python tools/verify_chain.py <folder of session files>
```

The last line says `chain verifies` (exit code 0) or `chain BROKEN` (exit code 1). Lines above it explain:

| Line | Meaning |
| --- | --- |
| `BROKEN … record content does not match its hash (changed)` | That record was altered after it was written. |
| `BROKEN … missing record(s) N to M before this line` | Records were deleted. |
| `BROKEN … prev does not match the previous record (chain broken)` | Records or whole files are missing or out of place. |
| `BROKEN … file does not start with session_start` | The start of a file was removed. |
| `NOTE … truncated last line` | Power was lost while a record was being written; the logger never rewrites it. Not a failure. |
| `NOTE … declared chain break: new card` | The card was replaced; the new card starts a new chain. Not a failure; the laptop's last hash from the old card keeps the gap visible. |
| `NOTE … newest session has no session_end` | The session is still running, or did not end cleanly. |
| `unknown format` (exit code 2) | The files come from a newer logger; use a matching version of the tool. |

**If the chain check fails:** do not edit or delete the files. Keep the retrieved folder read-only and make a copy for analysis. Note the first broken record (file and line), and compare the chain with the last hash the laptop kept from the previous retrieval: anything before that hash was already verified. Report it with the logger's VIN and the session numbers to the escalation contact *(to be agreed with ORNL)*.

### Opening raw captures

For each new connection and each control-flag event, the logger saves the raw CAN frames from 10 s before to 60 s after it in `raw/`, named by session, connection and event number (for example `s000142_c2_e1.log`). The connection record names its capture. The files are in `candump` log format: plain text, one frame per line, with a timestamp, the interface and `ID#DATA`. Open them in a text editor, replay them on a Linux machine with `canplayer -I <file>`, or convert them with can-utils' `log2asc` for other CAN tools. Old captures are deleted first when the card fills: retrieved ones first, then unretrieved ones, oldest first.


## 5. Admin
- Logging in, file locations, starting and stopping the service, the diagnostic log *(step 8)*
- Installing, updating and rolling back from the release bundle *(steps 8, 9)*
- Adding and removing operator keys: an admin runs `release/keys.sh` on the logger, which installs the public key and keeps a fingerprint-to-name file *(step 8)*. Each session header lists the fingerprints of all installed operator keys.
- Updating the device library: characterize the device on the bench, add an entry to `src/j1939logger/data/device_library.json` (function codes, typical and never-used PGNs, optional make and model), raise the library version, install it with the release, then rerun the identification tests and record the new library version in the findings report's setup section. The repo source is installed on the logger as `library/lib-vN.json`; raising the library version means changing the `library` field (`lib-v1` → `lib-v2`); the format stays `lib-1`. *(The source file is created in step 8 from the bench characterization; until then `docs/examples/lib-v1.json` shows the format.)*
- The hardening checklist and the Beacon procedure *(step 8)*
- Deleting data by hand *(step 8)*

## 6. Reference
- Troubleshooting table: below
- Command reference: below
- Glossary, FAQ, escalation contact *(step 9)*

### Troubleshooting

<!-- troubleshooting:start -->
*Generated from `docs/errors.md` by `tools/troubleshooting.py`; edit that table, not this one.*

| Light | What happened | What the logger does | What to do |
| --- | --- | --- | --- |
| Fast blink | CAN interface: Missing at start, or `ENODEV`/`ENETDOWN` while running | Retry with backoff; fault after `can.bitrate_fault_s`; log once with a count, not per retry. Transmit: never. | Check the 9-pin cable and the tap, then run `status`; if the light stays fast, power-cycle the logger. |
| Off, then fast blink | CAN interface: No bit rate confirmed | Stay listen-only and keep trying; fault after 60 s. Transmit: never. | Check that the key is on and the 9-pin cable is seated, then run `status` again after a minute. |
| Fast blink | CAN interface: Bus-off; error-passive from its own transmit errors | Stop transmitting for the session; listen-only; keep detecting. Transmit: off for the session. | Check the tap wiring and termination; transmit stays off until the next session. Report the session number. |
| Fast blink | CAN transmit: `ENOBUFS` (transmit queue full, for example no other node to acknowledge) | Treat as a transmit error; no retry loop. Transmit: off for the session. | Check that the 9-pin cable is seated (no other node acknowledged); transmit stays off until the next session. |
| Fast blink | CAN transmit: A frame would break the allow-list or rate cap | Drop the frame; turn transmit off. Transmit: off for the session. | Report it with the session number: the logger stopped transmitting to protect the truck. |
| Unchanged | CAN receive: Kernel drops (`SO_RXQ_OVFL` count rises) | Count; notice fault if above zero during a session | Nothing to do now; if it repeats, report the session number (the bus may be too busy). |
| Unchanged | Frames: 11-bit IDs, remote frames, error frames, wrong data length for a known PGN | Count by type; never raise; error frames feed bus-error counts and bit-rate detection | Nothing to do; these frames are counted in the session end record. |
| Unchanged | Transport: Out-of-order or duplicate sequence numbers, missing packets, T1 to T4 timeouts (750, 1250, 1250, 1050 ms), aborts, too many open sessions, oversize transfers | Close the session and count the reason; for a transfer addressed to the logger, send Connection Abort; never raise. Transmit: abort only. | Nothing to do; transfer problems are counted. Report them if a device's records look incomplete. |
| Unchanged | Transport: ETP transfer (51200, 50944) | Log without reassembling; flag a memory transfer with DM14 to DM16 activity | Review the device's connection records; a memory transfer is flagged there. |
| Per severity | Address claim: Known NAME at a new address; Cannot Claim from another node; request for claim to a specific address | Confirm a move when the old address is silent within `detection.move_grace_s`; defined outcomes per DET-4 and DET-15; log, never raise. Transmit: continues (the logger concedes). | Review the event; if the move is expected, run `approve <event-id>` so it stops recurring. |
| Slow blink | Address claim: Same NAME at two addresses (old address still sending after the grace, or both answer a sweep) | Treat as a possible copied NAME; keep both addresses tracked | Run `events` and report the event ID: two devices may be using one ECU's identity. |
| Fast blink | Storage: `ENOSPC`, `EROFS`, `EIO`, card removed (`ENODEV`), slow sync | LOG-22 path: high fault; reopen after reinsertion; sync on its own thread; never block capture | Reseat or replace the card, then run `status`; run `retrieve` as soon as the card works. |
| Slow blink | Storage: Card nearly full | Free space in the agreed order: retrieved raw captures, then unretrieved, oldest first (DC-20); with only the reserve left, raw captures stop (high fault) | Run `retrieve` so the logger can free retrieved raw captures; replace the card if it stays nearly full. |
| Fast blink (fault) or slow blink (untrained) | Storage: Truncated last line; leftover temporary files; corrupt inventory, config or device library | Report truncated; ignore temporary files; corrupt inventory runs untrained; corrupt config stops with a fault; corrupt device library: high fault, identification continues without it (DC-19). Transmit: per state. | Corrupt config: `config push` a good one. Corrupt inventory: `train start`. Corrupt library: reinstall the release. |
| n/a | Storage: Card not ext4 | Refuse to install | Format the card as ext4 and run `install.sh` again (see the porting guide). |
| Unchanged | Storage: `state.json` missing, corrupt or not writable on internal flash | Missing, with a blank card: a new logger. Missing or corrupt, with sessions on the card: continue numbering and the chain from the newest session file (LOG-5). Corrupt, with a blank card: notice fault; start as a new logger (`retrieve` keeps any same-named files, LAP-5). Not writable: notice fault; `install.sh` asks for the next session number when a new card is fitted | Run `status`; if the session number looks wrong, report it (`install.sh` asks for it when needed). |
| Unchanged | Clock: RTC invalid; vehicle time arrives mid-session; vehicle time far off; clock jump | Keep a vehicle-time offset; never set the system clock while running; skew fault above `clock.max_skew_min` | Nothing to do unless the clock stays invalid; `status` shows its source and its difference from the laptop. |
| Off while restarting | Service: Unhandled exception; hang | Write a stack trace to the diagnostic log; exit non-zero so systemd restarts it. Transmit: per next session. | Wait for the logger to restart; if it keeps restarting, run `retrieve` and report the diagnostic log. |
| Fast blink | Service: Restart loop | Start listen-only with no claim, sweep or requests until an operator runs `restart`. Transmit: off until `restart`. | Run `retrieve`, then `restart --reason ...` once the cause is fixed; transmit stays off until then. |
| Unchanged | Commands: Service not running; a second operator at the same time; invalid ID; wrong state (for example `train finish` when not training); unknown protocol version | Refuse with the reason and the next step; non-zero exit code; commands handled one at a time | Follow the Next step line in the message; for "logger not running", power-cycle the logger. |
| n/a | Laptop: SSH host-key change, wrong passphrase, timeout, dropped link, Windows long paths, read-only folder | Clear message and next step for each; resume retrieval; never mark a half-copied file complete | Check the cable and the laptop's address; accept a new host key only if the logger was replaced; use a shorter folder for long paths. |
| n/a | Laptop: Retrieved file has the same name as one already retrieved, with different content | Keep both: rename the new file with a suffix, never skip it; report it | Nothing to do; both copies are kept and the report names the renamed file. |
| n/a | Laptop: Cannot connect | Message names the fixed address (`network.address`) and the cable check | Check the Ethernet cable and that the laptop got a 192.168.250.x address, then run `status`. |
<!-- troubleshooting:end -->

### Command reference

Run `j1939ctl <command> --help` for every option. Commands that change the logger show what will change, ask for a reason (or take `--reason`) and ask y/N (or take `--yes`). Exit codes: 0 done, 1 refused or declined, 2 usage, 3 logger not reachable or not running.

| Command | What it does |
| --- | --- |
| `status` | Home screen: state and light, VIN, session, events to review, whether training is needed, card use, clock and its difference from the laptop, versions, and a Next step line. Works when the logger service is down (last saved status). |
| `train start` / `train status` / `train finish [--pto]` | Start training; show the time used and left, the conditions covered and the devices found; finish, show the proposed inventory by entry ID and ask whether to apply it. |
| `events [--all]` | List the events to review by event ID (for example 142-37), in plain words. |
| `approve <event-id>` | Approve a logged device, a new PGN (with a warning line for a control PGN) or a moved address; clears the event; saves a new inventory version for the next session. |
| `remove <entry-id> [--pgn N --direction sent\|requested]` | Remove a device, or one PGN, from the inventory from the next session (a warning line for an ECU found in training). |
| `clear <event-id>... [--disposition TEXT]` | Mark high events as reviewed with one reason. |
| `config show` / `config push <file> [--confirm]` | Show the active config, or check a new one on the laptop and send it; a change that weakens detection needs `--confirm`. |
| `inventory show` / `inventory export [--out FILE]` | Show the inventory, or write it as CSV; `--from-folder DIR` works on a retrieved folder without the logger. |
| `retrieve` | Copy new files into `logs/<VIN>/`, check the chain, make the folder read-only and record the retrieval on the logger. |
| `report <folder>` | Write the five-section report and `events.csv` from a retrieved folder; works offline. |
| `restart` | Restart the logger software (the next session records it). |
| `retrain` | Archive the inventory and run untrained from the next session until a training is applied. |

## Appendix: quick card *(step 9)*
