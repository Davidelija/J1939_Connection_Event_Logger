# J1939 event logger: user manual

Skeleton. Each section is filled in by the build step that delivers its feature (hand-off, Documentation to deliver) and finished in step 9 with real bench output. Each task gives when to do it, the steps, example screen output and what can go wrong.

## 1. Getting started

### What the logger does

The logger sits on a short tap at a heavy truck's 9-pin J1939 diagnostic connector. During training it learns which devices normally sit on the vehicle network. After that it watches every session, from key-on to key-off, for anything new: an ELD, a scan tool or any other device.

**What it records.** For each new device: when it connected and disconnected, its address and NAME, what kind of device it seems to be, what it sent and what it asked for. It also records raw CAN frames from 10 s before to 60 s after each new connection. Records are hash-chained, so a changed or missing record shows up when the logs are checked.

**What it sends.** Only a small, fixed set of frames: its own address claim (always at an address from 128 to 247, and it always gives way in a conflict), and requests for address claims, the vehicle's time and date, the VIN, and the identity of new devices, plus the replies J1939 requires of every node (answering a request for its address claim, refusing other requests addressed to it, and transport-protocol handshakes for replies sent to it). It sends at most 10 frames a second.

**What it never does.** It never sends a command, a clear or a write, and never gives data to other devices. It does not use Wi-Fi or Bluetooth. It never deletes its event logs, not even after retrieval.

**Where the data goes.** Everything is written to the logger's card. A maintenance laptop retrieves the logs over a wired SSH connection, checks the chain and produces a report for review.

*(The rest of this chapter is written as each build step lands.)*

- What you need *(step 7)*
- What you need *(step 7)*
- Running the no-hardware demo *(below)*

### Running the no-hardware demo

**When:** to see the logger work before you have hardware, or to check a new copy of the software.

**You need:** a Linux machine or virtual machine with Python 3.9 or later, `sudo` rights (to load the virtual CAN module), and can-utils (`sudo apt-get install can-utils` on Debian or Ubuntu).

**Steps:**

1. Get the repository and change into its folder.
2. Run `bash demo/run_demo.sh`.

The demo brings up a virtual CAN interface (`vcan0`), starts the logger listening only, replays a recorded capture in which a scan tool joins the bus, stops the logger, checks the hash chain and lists the records written. It ends with:

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
- Setting up the Windows laptop and connecting it: the logger's fixed address (`network.address`) and its DHCP server on the wired port *(step 7)*
- Installing the logger, including the VIN request address `requests.vin_sa` (default 0, the engine) *(step 8)*

## 2. Everyday use
- The status light and the `status` screen *(steps 7, 8)*
- Training a truck; PTO is detected from Power Takeoff Information 1 (PGN 65264, engaged when Power Takeoff Speed is above zero) or declared by the operator *(step 6)*
- Reviewing new events *(step 7)*
- Changing the inventory *(step 6)*
- Retrieving logs and running the report *(step 7)*
- Reading the report *(step 7)*
- Changing a setting *(step 7)*

## 3. Less common tasks
- Restart or retrain *(step 7)*
- Moving the logger to another truck by hand *(step 8)*
- Replacing the card or removing the logger; the card is ext4, so card-swap retrieval needs a Linux machine or VM; the new card starts a new chain, which the chain check reports as a declared break; session numbers carry on from the logger's internal flash (if that isn't writable, `install.sh` asks for the next session number) *(step 8)*

## 4. For analysts

### The files on the card

The card is formatted ext4. On it:

| Folder or file | What it holds |
| --- | --- |
| `sessions/` | One event file per session: `s000142_20261106T140211Z.jsonl` (session number and UTC start). A session longer than 24 hours continues in parts (`…_p2.jsonl`). A session started with no valid clock is named `…_noclock.jsonl`. |
| `raw/` | Raw CAN frames around each new connection, in candump format *(from step 6)*. |
| `inventory/`, `config/`, `library/` | One file per version of the inventory, config and device library (`inv-v2.json`, `cfg-v3.json`, `lib-v1.json`). Old versions are kept. |
| `status.json` | The logger's current state *(from step 7)*. |
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

- Opening raw captures *(step 6)*

## 5. Admin
- Logging in, file locations, starting and stopping the service, the diagnostic log *(step 8)*
- Installing, updating and rolling back from the release bundle *(steps 8, 9)*
- Adding and removing operator keys *(step 7)*
- Updating the device library: characterize the device on the bench, add an entry to `data/device_library.json` (function codes, typical and never-used PGNs, optional make and model), raise the library version, install it with the release, then rerun the identification tests and record the new library version in the findings report's setup section. The repo source `data/device_library.json` is installed on the logger as `library/lib-vN.json`; raising the library version means changing the `library` field (`lib-v1` → `lib-v2`); the format stays `lib-1`. *(step 5)*
- The hardening checklist and the Beacon procedure *(step 8)*
- Deleting data by hand *(step 8)*

## 6. Reference
- Troubleshooting table, generated from `docs/errors.md` *(each step adds its rows)*
- Command reference *(step 7)*
- Glossary, FAQ, escalation contact *(step 9)*

## Appendix: quick card *(step 9)*
