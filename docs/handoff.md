# J1939 Event Logger: Claude Code Hand-off

Nov 9, 2026 · @Vaughan

## Purpose and source of truth

This doc tells Claude Code how to build the J1939 connected-devices event logger: what to build, in what order, how to test it, and the rules it must not break. It is exported to `docs/handoff.md` in the repository alongside the other specs.

**Reading order**

1. This hand-off (`docs/handoff.md`): decisions, layout, modules, build plan, rules.
2. Requirements (`docs/requirements.md`): every "shall", with IDs, verification method and status. Requirement IDs are the unit of work and of testing.
3. Log format (`docs/log-format.md`, from the Beacon doc): the authoritative schema for every file the logger writes.
4. Example files (`docs/examples/`): one worked session (session 142) showing every file type.
5. Background, read as needed, in `docs/background/`: detection methods doc (`detection-methods.md`), Beacon application doc (`beacon-application.md`) and architecture page (`architecture.html`, `architecture.png`).
6. Hand-over docs, written for the recipient rather than for Claude Code: `docs/transition.md` and `docs/porting.md`.
7. Error handling (`docs/errors.md`): every expected error and how the logger handles it.
8. Module contracts (`docs/modules.md`): inputs, outputs, errors and test seams per module, shared types, layering, the test integration contract and the contract freeze by build step.
9. Design change log (`docs/design-changes.md`): every change since the Nov 10 baseline; read it at the start of every session.

**Source of truth:** the requirements win, then `docs/log-format.md` on any field or record detail, then `docs/modules.md` on module boundaries, then this hand-off. Any disagreement is a defect to report, not to resolve silently.

## System summary

The logger sits on a short tap at a heavy truck's 9-pin J1939 diagnostic connector. It learns which devices normally sit on the bus (training), then watches every session for anything new: an ELD, a scan tool or any other device. For each new connection it records who it was, what it asked for and what it sent, in a tamper-evident log that a maintenance laptop retrieves and reviews.

**It does:**

- Receive every frame on one J1939 network at 250 or 500 kbit/s.
- Claim its own address (128 to 247, always conceding conflicts) and send a small, fixed set of requests: address-claim sweeps, Time/Date, VIN and identity requests.
- Detect new NAMEs, new source addresses, claim conflicts, control PGNs and diagnostic activity; identify devices by type and make.
- Write one hash-chained JSON-lines file per session, plus raw frames around each new connection.
- Show its state on one status light and take training, approvals, config and retrieval only from an authenticated maintenance laptop over SSH.

**It never does:**

- Transmit anything outside the allow-list: no commands, no clears, no writes, no data for other nodes.
- Exceed 10 frames per second of its own traffic.
- Use wireless networks.
- Delete logs on retrieval, or delete event files at all.
- Change its transmit allow-list through configuration (that needs a software release).

## Design decisions

These were settled on Nov 6, 2026 and are already reflected in the requirements.

| # | Decision | Requirements |
| --- | --- | --- |
| D1 | Python 3 throughout. Frame capture is a separate module (frames in, timestamped records out) so it can be rewritten in C if the bench test drops frames. Capture reads SocketCAN with the standard socket module (AF\_CAN, CAN\_RAW, recvmsg with SO\_TIMESTAMP) on its own thread into a preallocated ring buffer; the receive buffer is set with SO\_RCVBUFFORCE and read back; the per-socket drop count comes from SO\_RXQ\_OVFL; python-can only as an optional platform input (X22). Raw CAN sockets with our own J1939 handling (address claiming, transport protocol) are the default; the kernel J1939 driver is an optional later optimization. | SC-9, LOG-15 |
| D2 | Laptop talks to the logger over SSH (Ethernet or USB-Ethernet), one key per operator; the key identifies the operator. Laptop tool is a Python command-line program. Card swap is a manual backup for retrieval only and needs a Linux machine or VM, because the card is ext4 (X26). The logger has a fixed wired address and a DHCP server on that port (X29). | STS-4, STS-5 |
| D3 | Session ends after 30 s with no frames from any device; open connections end with reason key-off. | LOG-17 |
| D4 | Pass test: zero dropped frames at 60% load on a 500 kbit/s bus for 30 min with 2 s bursts at 100%. A 100% stress run is reported, not required to pass. | SC-9 |
| D5 | `connection_start` written and synced within 2 s of a new device's first frame; status light set to slow blink at the same time. | DET-16 |
| D6 | Untrained mode until a confirmed inventory exists: record everything, cap severity at notice, needs-training light. | TRN-9 |
| D7 | VIN requested at every session start; a mismatch is high severity and switches the session to untrained mode. | NP-12, DET-14 |
| D8 | Approved external devices: requests outside their trained set logged at notice. Pending the ORNL check, like DET-12. | DET-12 |
| D9 | Logger transmits at most 10 frames/s, one outstanding request per destination, protocol responses first. | NP-16 |
| D10 | Retrieval never deletes. When space runs low: retrieved raw captures first, then unretrieved, oldest first; event files never removed automatically. | LOG-11 |
| D11 | Vehicle ECU not in baseline = claims within 10 s of the session's first frame, stays all session, sends no diagnostic requests. Otherwise external. Both are high (changed Nov 7). A trailer device (NAME vehicle system = trailer, no diagnostic requests, no control PGNs, no DM14 to DM18, no inventory ECU's address) is notice; breaking any of those makes it external, high. | DET-13 |
| D12 | Config pushed from the laptop, validated, versioned, logged, applied next session; additions to the transmit allow-list rejected. | STS-9 |
| D13 | Time from the real-time clock if valid, else vehicle Time/Date kept as an offset (the system clock is never changed while running), else time since wake; every timer uses the monotonic clock (X27); `clock_valid` and `clock_source` on every record. | LOG-16 |
| D14 | Connection keyed by NAME, or by SA for devices that never claim; a return after the end is a new connection. | DET-15 |
| H1 | Deploy by copying a tagged release bundle over SSH and running `install.sh` (signed update and rollback deferred); run as a systemd service that starts at boot and restarts on failure. | Open check |
| H2 | Private GitHub repo; pytest; replay tests on `vcan0`; tests run on every push; requirement IDs in test names. | All T items |
| H3 | Build a thin end-to-end slice first, then widen in nine steps (Build plan below). | All |
| H4 | This doc was reviewed as a Claude Doc and exported to `docs/` with the requirements and log format; a short `CLAUDE.md` points to them. From Tuesday, Nov 10, 2026 the repo's `docs/` is the only copy: the specs are edited only there, and the Claude Docs, Word and text versions are frozen and marked superseded (amended by X19). | n/a |
| L1–L8 | Laptop tool: Windows (Linux deferred); fixed command set acting on stable event and entry IDs; required reason to clear; one VIN folder per logger with incremental, resumable retrieval and a chain check; plain-text report; keys installed by `release/keys.sh` and listed by fingerprint in session\_start. See Laptop tool commands. | LAP-1 to LAP-6, LAP-8 |

### Decision log

Every ID cited in the requirements' Source column is defined here or in the table above (D1–D14, H1–H4). Each row gives the final state of the decision.

| ID | Decision (final state) | Requirements |
| --- | --- | --- |
| L1 | Laptop tool runs on Windows with the Windows OpenSSH client; Linux deferred | LAP-1 |
| L2 | A fixed set of 16 commands | LAP-2 |
| L3 | Commands act on stable event and entry IDs | LAP-3 |
| L4 | One folder per logger, named by VIN; incremental retrieval with a chain check | LAP-5 |
| L5 | Plain-text report | STS-7 |
| L6 | Clearing needs a reason | LAP-4 |
| L7 | Operator keys installed by `release/keys.sh`; fingerprints listed in session_start | LAP-8 |
| L8 | Retrieval resumes after a dropped link | LAP-6 |
| P1 | One PGN at a time can be approved for one device, from its logged event | TRN-10 |
| P2 | PGNs approved later are kept separate from trained PGNs | TRN-13 |
| P3 | Approval covers PGNs sent and PGNs requested | TRN-10 |
| P4 | Nothing is added to the inventory automatically | TRN-11 |
| P5 | Approving a control PGN shows a warning line; approved control PGNs are counted, not flagged | TRN-10 |
| T1 | train finish reports the conditions covered and PGNs per ECU | TRN-12 |
| T2 | Training follows a written procedure, now in the user manual | Deliverables |
| A1 | Fleet profiles are future work; the inventory records the vehicle configuration | TRN-13 |
| A2 | Device library changed only by a push from the laptop; deferred, the library is copied with the software | IDN-7 |
| E1 | Inventory export as CSV | LAP-13 |
| RS1 | Reset commands: restart and retrain built; move deferred | STS-11 to STS-13 |
| RS2 | wipe, the only way to delete event files; deferred | STS-14 |
| TR1 | Trailer devices are classified separately at notice severity while they only broadcast | DET-18 |
| Review C1 | Approved external devices get info-level connection records | DET-17 |
| Review C2 | With no confirmed bit rate the logger never transmits and faults after 60 s | NP-17 |
| Review C4 | A software restart starts a new session that records the restart | LOG-18 |
| Review C5 | Retrieving an open session copies complete records only | LAP-9 |
| Review RD1 | The laptop never sets the logger clock; status shows the difference | LAP-10 |
| Review RD2 | approve needs a reason and clears its event | LAP-11 |
| Review RD3 | report and inventory show work offline on a retrieved folder | LAP-12 |
| Review RD4 | Failed SSH login counting; deferred | STS-10 |
| Review of requirements | A standalone chain verifier | LOG-14 |
| Usability review U1 | Stable event and entry IDs with confirmation | LAP-3 |
| Usability review U2 | Install procedure and quick guide, now chapters of the user manual | Deliverables |
| Usability review U3 | train status during training | LAP-14 |
| Usability review U4 | One status light with three patterns, fast blink winning | STS-1 |
| Usability review U5 | Refusals say why; --help; exit codes; --dry-run deferred | LAP-15 |
| Usability review U6 | Repeated events grouped in the report; clear by device and event filters deferred; clear takes several IDs | STS-7, LAP-4, LAP-16 |
| Usability review U7 | events.csv alongside the report | STS-7 |
| Usability review U8 | remove for devices and single PGNs | TRN-14, TRN-15 |
| Usability review U9 | Second pass: 16 commands, one prompt pattern, status as home screen, five-section report, plain-word output | LAP-2, LAP-3, LAP-10, LAP-17 |
| Maintainability review M1 | Signed update and rollback; deferred, software is copied over SSH | STS-15, STS-16 |
| Maintainability review M2 | Format version on every file, with a format history | LOG-19 |
| Maintainability review M3 | Configs with unknown or missing keys are rejected; checked on the laptop; migration deferred | STS-9, STS-17 |
| Maintainability review M4 | A separate diagnostic log | LOG-20 |
| Maintainability review M5 | The manufacturer list lives in the device library | IDN-2 |
| Maintainability review M6 | Verification matrix with a CI check | Deliverables |
| Maintainability review M7 | Pinned dependencies | Deliverables |
| Maintainability review M8 | New-card chain start; deferred | LOG-21 |
| Reliability review R1 | Watchdog heartbeat | STS-18 |
| Reliability review R2 | Event reserve on the card; internal flash fallback deferred | LOG-22 |
| Reliability review R3 | An incomplete last line is reported as truncated, never rewritten | LOG-5, LOG-14 |
| Reliability review R4 | Atomic writes for supporting files | LOG-23 |
| Reliability review R5 | Transmission turns off on error-passive or any transmit error | NP-3, NP-18 |
| Reliability review R6 | 24-hour soak; 7-day soak deferred | SC-10 |
| Reliability review R7 | Scenario suite with pass criteria | SC-11 |
| Reliability review R8 | Up to 2 s of records can be lost on power loss (known limitation) | Known limitations |
| Reliability review R9 | Start-up self-check; a corrupt config faults, a corrupt inventory runs untrained | STS-19 |
| Security review S1 | Signed seals; deferred | LOG-24 |
| Security review S2 | Beacon hardening as an install checklist | STS-20 |
| Security review S3 | Bus input limits; flood record and fuzz test deferred | DET-19, SC-12 |
| Security review S4 | Operator and admin roles and signed releases; deferred | STS-21, STS-22 |
| Security review S5 | Config changes that weaken detection need --confirm and are logged high | STS-9 |
| Security review S6 | Reviewer sign-off in the report instead of a two-person rule | STS-7 |
| Security review S7 | Ed25519 keys with passphrases, removed by an admin | LAP-8 |
| Security review S8 | Login throttling; deferred | STS-10 |
| Security review S9 | Threat model | Deliverables |
| SR1 | Scope reduction (Nov 7): requirements marked Deferred are kept with their IDs and not built | Future work |
| Transition review X1 | Platform requirements (PLT-1 to PLT-8) separate what any hardware must provide from Beacon facts; HW-4 and HW-9 keep the need, and the Beacon figures move to the Beacon doc | PLT-1 to PLT-8, HW-4, HW-9 |
| Transition review X2 | One platform layer (src/j1939logger/platform/) holds all hardware-specific code, with desktop and Beacon implementations and a porting guide | Constraints, Modules, rule 12 |
| Transition review X3 | Tests split into unit, replay and malformed-input; bench/ holds platform-neutral acceptance tests A1 to A8 | Testing |
| Transition review X4 | Basic malformed-input tests (Hypothesis) are active; the full fuzz campaign stays deferred | SC-12a, SC-12 |
| Transition review X5 | The verification matrix records where each requirement was verified (vcan, Beacon, not verified) and its result, updated every step; SC-9 CPU, memory and drop figures are recorded | Deliverables, SC-9, PLT-7 |
| Transition review X6 | Tagged releases with a changelog, an offline install bundle and an install script; docs/ is the authoritative source with a PDF snapshot per tag; no licensed content ships | Deliverables, IDN-2, rule 13 |
| Transition review X7 | User manual skeleton in step 1, filled in at each step; one human-review line per step in docs/reviews.md; ruff, mypy and a coverage report in CI | Deliverables, Build plan |
| Transition review X8 | A transition overview for the recipient, including what to obtain, decisions left to them and no support after the semester | Deliverables |
| Transition review X9 | The hand-over goal is Beacon-proven: build step 8 is the target and every Beacon open check is closed (amended by X12: a vcan fallback with recorded gaps) | Demo subset, Build plan |
| Transition review X10 | The code is provided under the MIT License | Release |
| Round-2 review X11 | The background docs (Beacon doc, detection doc, architecture page) are handed over in docs/background/, as they stand; every reference points there | Conventions, Referenced specifications, LOG-8, STS-20 |
| Round-2 review X12 | A Beacon-proven build is the goal; if a Beacon check fails or time runs out, the vcan build is handed over with the Beacon results so far and each gap recorded (amends X9) | Constraints, Demo subset, Deliverables, Build plan |
| Round-2 review X13 | Cut line: (1) functional core on vcan; (2) A1 to A4 on the Beacon; (3) A5 to A8, SC-10, SC-11. The hand-over documents are produced at whatever tier is reached | Demo subset, Build plan |
| Round-2 review X14 | PTO from PGN 65264, Power Takeoff Information 1 (PTO1), engaged when Power Takeoff Speed (SPN 186) is above zero; otherwise declared by the operator | TRN-12 |
| Round-2 review X15 | DET-13's request rule stays as written and is checked against rig captures in build step 5 | DET-13, Open items |
| Round-2 review X16 | The VIN request address is a config setting, requests.vin_sa (default 0), set at installation; format stays cfg-1 | NP-12, Configuration |
| Round-2 review X17 | The Demo subset gains NP-3, NP-17, NP-11 and LOG-17 | Demo subset |
| Round-2 review X18 | The Beacon open checks run before build step 3 as a go/no-go (step 2a) | Build plan, Open items |
| Round-2 review X19 | The repo's docs/ becomes the only copy on Tuesday, Nov 10, 2026; the Claude Docs, Word and text versions are frozen and marked superseded (amends H4) | Deliverables, H4 |
| Round-2 review X20 | A minimum acceptance setup lets A1 to A8 run without a vehicle or rig ECUs | porting.md, transition.md |
| Final review X21 | Backup platform named and budgeted: a Linux single-board computer, a CAN interface with a mainline SocketCAN driver and a battery-backed RTC, bought only if the Beacon fails the go/no-go | Build plan step 2a, porting.md |
| Final review X22 | Capture reads SocketCAN with the standard socket module on its own thread into a ring buffer; SO_RXQ_OVFL drop count; SO_RCVBUFFORCE buffer read back and logged; python-can only as an optional platform input | D1, LOG-15, PLT-2, capture, rawcap |
| Final review X23 | The service is the only writer; laptop commands reach it through a logger-side command program and a Unix socket, JSON with a protocol version, one at a time | STS-23, Command path |
| Final review X24 | Operator identity from the SSH key fingerprint (ExposeAuthInfo) and a fingerprint-to-name file kept by keys.sh; a forced command per key is future work | STS-5, LAP-8, STS-20 |
| Final review X25 | Restart-loop protection: after 3 unclean restarts in 10 minutes the next session starts listen-only with transmit off | NP-19, STS-1 |
| Final review X26 | ext4 card, one write() per record with O_APPEND, directory synced after each rename; card swap kept, needing a Linux machine or VM | LOG-3, LOG-23, PLT-5, D2 |
| Final review X27 | Monotonic clock for every timer; system clock set only at boot from a valid RTC; vehicle time kept as an offset; NTP off | LOG-16, D13, STS-20 |
| Final review X28 | ETP recognized and logged, not reassembled; 11-bit, remote and error frames counted by type; format stays log-1 | DET-10, DET-19, LOG-7 |
| Final review X29 | The logger has a fixed wired address and a DHCP server bound to that port | STS-5, STS-20 |
| Final review X30 | Findings (validation) report, docs/findings.md, to findings-report-spec.md; scoring scripts in a separate chat | Deliverables |
| Final review X31 | No-hardware demo, demo/run_demo.sh, from build step 2, run in CI | Deliverables, Build plan |
| Final review X32 | Test devices: use what the team has; the findings report states the limitation | IDN-5 |
| Final review X33 | No separate dataset deliverable; the fixtures in tests/ are enough | n/a |
| Final review X34 | Recorded walkthrough, optional, in step 9 | Deliverables |
| Final review X35 | No separate note to ORNL; transition.md states the out-of-scope items and what the recipient needs | transition.md |
| Final review X36 | Error-handling table docs/errors.md, with fault-injection tests and a generated troubleshooting table | Testing, rules 11 and 14 |
| Final review X37 | Hardware buying guide in porting.md, as examples to evaluate | porting.md |
| Final review X38 | Transmitting is accepted; ORNL raised no concern | NP-9 |
| Final review X39 | Power draw and sleep are future research: HW-5 and PLT-4 Deferred; HW-8 stays | HW-5, PLT-4, Future work |
| Final review X40 | Confirm the MIT licence with CSU and the instructor near completion, before the first tag | Open items |
| Final review X41 | Extra go/no-go checks for step 2a | Open items, Build plan |
| Name-tracking review X42 | Detection follows NAMEs: addresses map to NAMEs each session from claims and sweeps, with inventory addresses as provisional matches until the first sweep and as identity for never-claiming entries; a move is confirmed when the old address is silent within detection.move_grace_s (1 s), otherwise a high same-NAME conflict; a new address is new against the inventory or earlier in the session, logged once per pair per session; `approve` adds a moved address; known_sa_new_pgn renamed known_device_new_pgn. No release has shipped, so the format stays log-1 (as X16, X28) (Nov 8). Follow-up: a first-sweep wait limit when no sweep can be sent (detection.first_sweep_wait_s, 10 s); a later frame from the old address raises the same-NAME conflict; move grace capped at 5 s and counted as detection-weakening; approval kind address | DET-2, DET-3, DET-4, DET-12, NP-4, NP-13, DET-18, TRN-10 |

## Repository layout

```
j1939-logger/
  CLAUDE.md                  standing rules (see Ground rules)
  README.md
  pyproject.toml             Python 3, standard library at run time (python-can optional extra); dev: pytest, hypothesis, ruff, mypy, pytest-cov, import-linter, python-can (test harness only)
  LICENSE                    MIT
  CHANGELOG.md               one entry per tagged release
  docs/
    handoff.md               this doc
    requirements.md          exported requirements
    log-format.md            exported Log format section
    errors.md                error-handling table (source of the troubleshooting table)
    modules.md               module contracts, shared types, layering, test integration contract
    design-changes.md        design change log (DC entries) from the Nov 10 baseline
    findings.md              findings (validation) report, step 9
    findings-report-spec.md  outline and scoring brief for findings.md
    findings-data/           tables and CSVs produced by tools/findings/
    background/              Beacon doc, detection doc, architecture page (HTML, PNG)
    examples/                session 142 example files
    user-manual.md           user manual (skeleton in step 1, filled in each step)
    transition.md            transition overview for the recipient
    porting.md               porting guide and platform interface
    reviews.md               one human-review line per build step
    test-report.md           bench and test results
    verification.md          verification matrix
    threat-model.md          threat model
  src/j1939logger/
    main.py                  service entry point; cmdserver (Unix socket)
    j1939cmd.py              logger-side command program called over SSH
    capture.py               frame capture (C-swappable)
    decode.py                ID split, transport protocol, NAME decode
    transmit.py              transmit queue, rate cap, allow-list
    address.py               address claiming and conflicts
    requests.py              sweeps, Time/Date, VIN, identity requests
    session.py               wake, key-off, session files, roll-over
    detect.py                connection state machine
    monitor.py               PGN, request, DM and control-flag records
    identify.py              classification and identification
    inventory.py             inventory, training, approvals
    eventlog.py              JSON lines writer, hash chain, sync (session files only)
    store.py                 supporting files: loading, atomic writes, state.json on flash
    rawcap.py                pre-event window from the capture ring, candump writer
    retention.py             card-space management
    clock.py                 clock source and validity
    status.py                status file and status light
    config.py                load, validate, version
    admin.py                 restart, retrain, diagnostic log, self-check
    platform/
      interface.py           the platform functions (see porting guide)
      desktop.py             vcan0 implementation, used by all tests
      beacon.py              DG Beacon implementation
    data/
      device_library.json    device library source; installed as library/lib-vN.json
  tools/
    j1939ctl/                laptop command-line tool
    verify_chain.py          standalone chain verifier
    anonymize_capture.py     scrubs VINs and serial numbers from candump files before they go in tests/fixtures/rig/
    findings/                findings-report scoring scripts (separate chat)
    fixtures/                scenario.py: one scenario description → a fixture folder and its findings ground truth (DC-4)
  tests/                     levels as in docs/modules.md §5 and docs/test-plan.md §2
    unit/                    level 1: module public functions (developers)
    contract/                level 1: Protocol conformance, public-name imports; import-linter layering config (developers)
    malformed/               level 1: generated malformed frames and transfers (SC-12a)
    component/               level 2: session in-process with fixture folders, FakeClock and the fault plan (test-script writers)
    replay/                  level 3: service on vcan0, witness, ecu_sim, j1939cmd over ssh localhost (test-script writers)
    harness/                 witness, ecu_sim, logger_proc, records, frames (test-script writers)
    fixtures/                fixture folders (traffic.log, manifest.json); rig/ holds rig captures, VINs anonymized
  bench/                     level 4: acceptance tests A1 to A8 (platform-neutral); B-HW1, B-HW3, B-PLT2, B-STS20, B-SN1; SC-9, SC-10 and SC-11 run sheets
    checklists.md            every D, I and A requirement with step, observer and evidence
    tools/                   scripted address-claim contender for A3
  demo/
    run_demo.sh              no-hardware demo on vcan0; also the CI smoke test
  .github/pull_request_template.md   definition of done and the state block
  .github/CODEOWNERS         human review for transmit, config, eventlog, platform, docs
  .github/workflows/ci.yml   vcan0 tests, ruff, mypy, coverage, demo, verification check
  release/
    install.sh               offline install; checks ext4, raises rmem_max, hardening
    keys.sh                  operator keys and the fingerprint-to-name file
    j1939-logger.service     RestartSec and start limits (NP-19)
    wheelhouse/              built per release, pinned by hash
```

## Modules

The modules follow the software boxes on the architecture page. Data flows capture → decode → detection modules → event log; everything the logger sends goes through `transmit`. This table is a summary; each module's full contract (inputs, outputs, errors, config keys, test seam) is in `docs/modules.md`, which wins on module boundaries.

| Module | Responsibility | Requirements |
| --- | --- | --- |
| `capture` | Frames in, timestamped records out; the only receiver. | SC-2, NP-1 to NP-3, NP-17, LOG-15 |
| `decode` | Raw frames to J1939 messages; TP reassembly; counts of frames that aren't J1939. | NP-9, NP-15, IDN-1, DET-10 (ETP), DET-19 (transfer limits, malformed and non-J1939 frames) |
| `transmit` | The only path to the bus; allow-list, rate cap, transmit off on any breach. | NP-3, NP-9, NP-16, NP-18 |
| `address` | The logger's own address claim; always concedes. | NP-4 to NP-8, DET-4 |
| `requests` | Sweep, Time/Date, VIN and identity requests; timeouts and outcomes. | NP-11 to NP-14, DET-14 |
| `session` | Session lifecycle and the main loop; self-check, watchdog, restart guard. | LOG-1, LOG-2, LOG-6, LOG-12, LOG-17, LOG-18, TRN-9 |
| `detect` | Connections by NAME (or SA); address-to-NAME map; moves and conflicts. | DET-1 to DET-6, DET-15 to DET-17 |
| `monitor` | What each connected device sends and requests; control flags. | DET-7 to DET-12 |
| `identify` | Category, type, make, model and confidence; device library scoring. | DET-13, DET-18, IDN-2 to IDN-7 |
| `inventory` | Known-good devices; training, approval, removal, versions. | TRN-2 to TRN-7, TRN-10 to TRN-15 |
| `eventlog` | The only writer of session files; hash chain; sync thread. | LOG-3 to LOG-5, LOG-7 to LOG-9 |
| `store` | The only writer of supporting files (status, inventory, config, library, `state.json`); loading; atomic writes. | LOG-5, LOG-13, LOG-23, TRN-6, STS-3 |
| `rawcap` | Raw candump windows around events, from the capture ring. | LOG-10 |
| `retention` | Card space: decides what may be freed; warnings. | LOG-11 |
| `clock` | The only source of time; vehicle-time offset; monotonic timers. | LOG-16 |
| `status` | Status file and the one status light. | STS-1 to STS-3 |
| `config` | Validate and version config; validate inventory and library files. | LOG-13, STS-9 |
| `j1939ctl` (laptop) | Operator tool on Windows; the 16 commands; report; chain check. | STS-5, STS-7, STS-9, STS-23, TRN-4 to TRN-6, LAP-1 to LAP-15, LAP-17 |
| `verify_chain` | Standalone chain verifier. | LOG-14, LOG-19, LAP-5, LAP-9 |
| `admin` | Restart, retrain, diagnostic log. | STS-11, STS-12, LOG-20 |
| `platform` | The only hardware-specific code; desktop and Beacon implementations. | PLT-1 to PLT-8, HW-7, HW-8, STS-1, STS-18 |
| `cmdserver` (in `main`) | The command socket; one command at a time. | STS-23 |
| `j1939cmd` (logger side) | Logger-side command program called over SSH. | STS-5, STS-23, LAP-15 |

## Laptop tool commands

`j1939ctl` runs on Windows with Python 3 and the Windows OpenSSH client (LAP-1); keep it free of Windows-only code so Linux can be added later. Each command that changes the logger is logged there with the operator taken from the SSH key.

| Command | Arguments | Refused unless | What it does and logs | Requirements |
| --- | --- | --- | --- | --- |
| `status` | none | none | Home screen: state, VIN, session, unreviewed events, whether training is needed, card use and write totals, clock OK and its difference from the laptop clock, config, inventory and library versions, installed operator key fingerprints, and a "Next step" line (for example "3 events to review: run events") | STS-3, LAP-10 |
| `train start` | none | Not already training | Starts training; logs `training_start` | TRN-2, TRN-3 |
| `train status` | none | Training active | Shows elapsed and remaining time, conditions covered so far, devices found and PGN counts per ECU | LAP-14 |
| `train finish` | none | Training active | Ends training; shows the coverage summary and the proposed inventory by entry ID, then asks "Apply this inventory? y/N"; logs `training_finish`, then `approval` or `rejection` | TRN-4, TRN-6, TRN-12 |
| `events` | `--all` to include reviewed events | none | Lists unreviewed events by event ID (for example 142-37) in plain words: what happened, NAME, address, make, PGNs sent, requests made | LAP-3, LAP-17 |
| `approve <event-id>` | `--reason` (or asked at the prompt) | The event is a device connection, a new-PGN event or a notice address\_change | Device event: adds the device to the inventory. Address\_change: adds the address to that entry's addresses. New-PGN event: adds that one PGN (sent or requested) to that device, with a warning line in the prompt for a control PGN. Clears the event; new inventory version; logs `approval` with its kind | TRN-5, TRN-10, LAP-11 |
| `remove <entry-id>` | `--pgn <n>` to remove one PGN; `--reason` (or asked) | The entry, or the PGN, is in the current inventory and is not the logger | Removes the device, or one PGN, from the inventory from the next session, with a warning line in the prompt for an ECU found in training; logs `inventory_remove` | TRN-14, TRN-15 |
| `clear <event-id>…` | `--reason` (or asked) | Each event is an unreviewed high event | Clears them; logs `review_clear` | STS-2, LAP-4 |
| `config show` / `config push <file>` | file path | Push: file validates and adds nothing to the allow-list | Shows the active config, or shows the changes and saves a new version applied next session; logs `config_change` or `config_rejected` | STS-9, STS-17 |
| `inventory show` / `inventory export` | `--folder` for a retrieved folder | none | Shows the inventory, or writes it as CSV; works offline | TRN-6, LAP-12, LAP-13 |
| `retrieve` | none | none | Copies new files into the logger's VIN folder, resumes after a dropped link, copies complete records only from the open session, then checks the chain; logs `retrieval` | LAP-5, LAP-6, LAP-9 |
| `report` | `--folder` | none | Writes the five-section report on screen and to a file, plus events.csv; works offline | STS-7, LAP-12 |
| `restart` | `--reason` (or asked) | none | Restarts the logger software; logs `reset` (restart) | STS-11, LOG-18 |
| `retrain` | `--reason` (or asked) | none | Archives the inventory and returns to untrained mode; logs `reset` (retrain) | STS-12 |
| `library push <file>` | file path | File validates | Deferred, do not build. Saves a new device library version | IDN-7 |
| `move` | `--reason`, new connector and network | A verified retrieval covers every session | Deferred, do not build. Archives the old vehicle's logs and inventory | STS-13 |
| `wipe` | `--reason` | A verified retrieval covers every session | Deferred, do not build. Deletes logs, inventories and archives | STS-14 |
| `update <package>` / `rollback` | `--reason` | Signed package; not training | Deferred, do not build. Installs a release or returns to the previous one | STS-15, STS-16 |

Every command that changes the logger (`train finish`, `approve`, `remove`, `clear`, `config push`, `restart`, `retrain`) works the same way: it shows in plain words what will change, asks for a reason (at the prompt or with `--reason`), then asks y/N; `--yes` skips the y/N for scripts. Risky changes (approving a control PGN, removing an ECU found in training) show a warning line in that same prompt. Every command has `--help`; a refusal says why and what to do, and the tool exits non-zero (LAP-3, LAP-15). Separate operator and admin roles (STS-21) are deferred: each person has one key, logged by fingerprint. A config push that weakens detection needs `--confirm` (STS-9).

Operator keys are installed and removed by `release/keys.sh`; each session\_start lists the installed key fingerprints (LAP-8). Retrieved files live in `<laptop data folder>/<VIN>/sessions`, `raw`, `inventory` and `config`, mirroring the logger. `inventory show` and `inventory export` display or save the active inventory (TRN-6). `report` and `inventory show` also run on a retrieved folder with no logger connected (LAP-12). Retrieving during a session copies complete records only (LAP-9). The tool never sets the logger's clock; `status` shows the clock difference (LAP-10).

### Command path

- Only the logger service writes the session file, inventory, config versions and status file (STS-23).
- `j1939ctl` runs each command over SSH as `j1939cmd <command>` on the logger. `j1939cmd` takes the operator from the SSH key fingerprint (OpenSSH `ExposeAuthInfo`, mapped to a name by the file `release/keys.sh` keeps) and sends the request to the service over a Unix socket (`/run/j1939-logger/cmd.sock`).
- Requests and replies are one JSON line each: `{"proto":1,"cmd":"clear","args":{"events":["142-5"]},"operator":"jdoe","reason":"RO 55812"}` and `{"proto":1,"ok":true,"result":{}}`, or `{"proto":1,"ok":false,"error":"…","next":"…"}`. Both sides refuse a protocol version they do not know.
- The service applies one command at a time; capture keeps running meanwhile.
- If the service is down, `status` reads the status file and `retrieve` copies files; changing commands are refused with "logger not running" and the next step (LAP-15).

## Build plan

Build in this order. A step is done when its tests pass in CI (with ruff and mypy) and a short demo runs on `vcan0`. Each step also updates its user manual sections and its rows in docs/verification.md, and adds a line to docs/reviews.md for a human reviewer. Each step also adds its rows to docs/errors.md and, from step 2, extends demo/run\_demo.sh. The full definition of done is the checklist in `.github/pull_request_template.md`. Steps 1 and 2 transmit nothing; transmit code starts in step 3, after the passive pieces are proven.

| Step | Scope | Done when |
| --- | --- | --- |
| 1. Thin slice | `capture`, `decode`, minimal `detect` and `eventlog`, the `platform` interface with its desktop implementation, and the user manual skeleton. Interface code comes first: `types.py`, `platform/interface.py` (as a `Protocol`), `FakeClock` and `DesktopPlatform` with its fault plan are merged before any logic, so test scripts can start the same day: receive-only on `vcan0`, detect a new address claim, write a chained `connection_start` record. | Replaying a candump file with a new claim produces a valid `connection_start` within 2 s (DET-1, DET-16, LOG-4, LOG-5). |
| 2. Sessions and chain | `session`, full `eventlog`, `verify_chain`, `config` loading: header, end record, parts and roll-over, chain across sessions, clock fields. | Two replayed sessions verify as one chain; a deleted record is reported; `demo/run_demo.sh` runs the session 142 scenario (LOG-1 to LOG-6, LOG-14, LOG-17). |
| 2a. Beacon go/no-go | Run the Beacon open checks on the unit (no code needed): `ip link show`, `ip -details link show`, `uname -r`, `/sys/class/leds`, the Python and pip check, a clock power-cycle test, the accounts, services and radios survey, and the X41 checks (who owns the CAN channels, berr-reporting and error-passive flags, `restart-ms 0`, termination, `rmem_max` and root, CPU, RAM and space, USB-Ethernet, card filesystem, listening services), internal flash writable (for `state.json`, LOG-5), and the boot clock check (the kernel sets the system clock from the RTC at boot, `hctosys`: after a power cycle with no network, `date` matches `hwclock` before the service starts). | Each result is recorded in the requirements' open items and `docs/verification.md`. If SocketCAN or listen-only fails on the Beacon, the hardware tier switches to the backup platform (X21, `docs/porting.md`); the vcan fallback (X12) applies only if that also fails. |
| 3. Transmit | `transmit`, `address`, `requests`: claiming, conflicts, sweeps, Time/Date, VIN, identity requests, rate cap, transmit guard. | A witness capture on `vcan0` shows only allow-listed frames within the rate cap; conflict scenarios concede correctly; nothing is sent before a bit rate is confirmed; bus-off and error-passive stop transmit for the session; a restart loop starts listen-only (NP-1 to NP-19). |
| 4. Detection | Full `detect` and `monitor`: new SA, replies to unknown, sweep changes, PGN tables, requests, control flags, DM, proprietary, 60 s end. | Replay fixtures for each DET requirement pass; malformed-input tests for decode and monitor pass (SC-12a). |
| 5. Identification | `identify`, device library, manufacturer list, classification rule, severity. | Fixtures for a scan tool, an ELD and a late-waking ECU classify correctly; a specific-product library entry is matched and reported with make\_source library; a near-tie between a specific entry and the generic one reports the type only (DET-13, IDN-1 to IDN-6); rig captures checked for vehicle ECUs that send requests, with the result and any rule change recorded (X15). |
| 6. Training and inventory | `inventory`, training mode and coverage summary, untrained mode, VIN mismatch, device and PGN approvals, `rawcap`, `retention`. | Train, confirm, approve and VIN-mismatch scenarios produce the right inventory versions and records (TRN-2 to TRN-15, DET-14, LOG-10, LOG-11); every raw capture's window contains its record's `utc`. |
| 7. Laptop tool | `j1939ctl`: SSH commands, retrieval, summary report, config push, clear, and restart and retrain with `admin`. | End to end against a logger on a desktop: retrieve, report, approve, remove, train status, push config, prompts and refusals (STS-4, STS-5, STS-7, STS-9, STS-23, LAP-1 to LAP-15, LAP-17). |
| 8. Beacon | `status` light, wake and ready time, clock fallback and the systemd service with restart-loop limits through the Beacon platform implementation; acceptance tests A1 to A8 and bench tests; SC-9 CPU, memory and drop figures; close the Beacon open checks. | Runs on Beacon 1 at boot from the release bundle; A1 to A8 and the bench procedures pass, including the SC-9 load test, the SC-11 scenario suite and the SC-10 24-hour soak; a restart loop starts listen-only (NP-19); every hardware-relevant T requirement has a Beacon result, or a recorded gap, in verification.md. The goal for hand-over (X9, amended by X12). |
| 9. Documentation | Finish the user manual and quick card with real output captured on the bench; transmit statement; test report; transition overview; porting guide; findings report (`docs/findings.md`, X30); recorded walkthrough if time allows (X34); tagged release (CHANGELOG, release bundle, PDF snapshot of docs/). | Someone who has not used the logger installs it, trains it and reviews an event using only the manual; every command and fault in the tool appears in the command reference and troubleshooting table; the release installs on a freshly prepared Beacon with only install.sh and no internet. |

**Cut line** (decision X13). Build in this order and stop where time runs out: (1) the functional core of the Demo subset passing on vcan with its tests; (2) acceptance tests A1 to A4 on the Beacon (or the backup platform); (3) A5 to A8, then the SC-10 24-hour soak and the SC-11 scenario suite. Whatever tier is reached, produce the transition overview (stating the tier), the user manual for what was built, the verification matrix, the findings report and a tagged release.

## Testing

- **Unit tests (pytest):** pure functions such as ID splitting, NAME decoding, transport reassembly, hash computation, classification rules and config validation.
- **Replay tests:** start the logger against `vcan0`, replay a candump fixture with `canplayer`, then check the session file, raw captures, inventory and status file. A second socket on `vcan0` records everything the logger sends, standing in for the witness Beacon.
- **Malformed-input tests (`tests/malformed`, SC-12a):** Hypothesis generates frames with bad lengths, out-of-order and oversize transport transfers, ETP transfers, 11-bit, remote and error frames, bad NAMEs and floods of new addresses; `decode` and `monitor` must raise no unhandled exception, keep running and stay within the DET-19 limits.
- **Formats and levels:** the fixture folder format, matching rules, injection points and the four test levels are in `docs/modules.md` §5; this section lists the scenarios, CI and acceptance tests.
- **Naming:** each test name starts with the requirement ID it verifies, for example `test_NP_14_request_timeout_and_retry`; tests of project tooling start with the DC ID that defines the tool (`test_DC_2_...`, DC-6). The test report is the verification record for every requirement marked T. `docs/verification.md` lists every requirement with its method, test or procedure step and result; a CI check fails if a T requirement has no test once its build step has merged (the Step column, DC-2), skipping rows whose status is Deferred; for step 8 requirements a `bench/` procedure ID satisfies it, and before a release tag every T row needs a passing test, a procedure with a result, or a recorded gap. The test plan is `docs/test-plan.md`. A second check fails a release while any `docs/errors.md` row still has a placeholder in its Test column.
- **Fault injection:** the desktop platform implementation can simulate every error in `docs/errors.md` (CAN interface lost, bus-off, ENOBUFS, kernel drops, storage errors, card removed, slow sync, clock jumps), so each row gets a unit or replay test named by its requirement ID.
- **Fixtures:** start from the session 142 example files. Add one candump fixture per scenario: new scan tool, approved ELD connecting, late-waking ECU, non-claiming device, address conflict, a Commanded Address to the logger's NAME (ignored, no address change), a replacement card (declared chain break), a known ECU at a new address (an address\_change record and no false new-PGN or reply events), baseline ECUs claiming before the logger is ready (no DET-2 or DET-3 events), a copied NAME at a free address while the real ECU keeps sending (high same-NAME conflict), an approved address move that does not recur, control PGN, control PGN late in a connection, VIN mismatch, untrained truck, key-off mid-connection, 24 h roll-over, software restart, no confirmed bit rate, PGN approval, training coverage, vehicle ECU not in baseline (high), trailer device (notice), a trailer NAME that sends a diagnostic request (reclassified high), device and PGN removal, an event arriving between events and approve, an unknown config key, an unknown format version, a capture hang, a nearly full and a full card, a failing card, a truncated last line, a corrupt inventory, a transmit error, many new NAMEs at once (input limits), an oversize transfer and a detection-weakening config. Rig captures go in `tests/fixtures/rig/` only after `tools/anonymize_capture.py` has scrubbed them.
- **Time:** inject wall-clock and monotonic time through the platform layer, including clock jumps, so tests can run 60 s silences, 10 minute sweeps and 24 h roll-overs in seconds.
- **CI:** GitHub Actions loads the `vcan` kernel module and runs all unit, contract, malformed-input, component and replay tests, ruff, mypy, import-linter, a coverage report (no threshold) and `demo/run_demo.sh` as an end-to-end smoke test on every push, on Python 3.9 (DC-1) until step 2a confirms the Beacon's version, with dependencies pinned by version and hash.
- **Acceptance tests (`bench/`):** platform-neutral written procedures that any platform must pass after porting, run on the rig with Beacon 2 (or any independent recorder) as witness and traffic source (`cangen`). Each has setup, steps, a pass criterion and a results line (date, platform, result, evidence file). A1 bit-rate detection (SC-2, NP-1); A2 listen-only start, then normal mode (NP-1, NP-2); A3 transmit-guard witness test (NP-3, NP-9, NP-16, NP-18, SC-4); A4 60% load with bursts, recording CPU, memory and drops (SC-9, PLT-7); A5 power loss and cranking brownout (HW-6, LOG-5, LOG-12, LOG-14); A6 wake and ready time (HW-8); A7 real-time clock across power loss (HW-7, PLT-3, LOG-16); A8 status light and watchdog restart (STS-1, STS-18, PLT-8). The minimum acceptance setup in `docs/porting.md` runs them without a vehicle. SC-11 replays the `tests/fixtures/` scenarios on the rig, and LAP-1 is checked by a manual procedure on a Windows laptop. `bench/` also holds the procedures for the other hardware requirements (B-HW1 tap stub, B-HW3 supply range, B-PLT2 CAN controller features, B-STS20 hardening, B-SN1 the `install.sh` next-session prompt) and `bench/checklists.md`, one item for every requirement verified by D, I or A (`docs/test-plan.md` §8 and §9).

## Documentation to deliver

Start the user manual skeleton in build step 1 and fill in each section as its step lands; finish everything in step 9 from real bench output. The repo's docs/ is the authoritative source, and each tagged release includes a PDF snapshot. Keep them short and task-based.

| Document | Audience | Contents |
| --- | --- | --- |
| User manual (`docs/user-manual.md`) with a printable quick card | Operators, installers, reviewers, admin | Outline below |
| Transmit statement (one page) | Fleets, OEMs, ELD vendors | Everything the logger sends on the bus, and that it sends no commands, clears or writes |
| Test report (`docs/test-report.md`, `docs/verification.md`) | Instructor, ORNL | Verification matrix with where each requirement was verified (vcan, Beacon, not verified) and its result; acceptance tests A1 to A8 on the Beacon; SC-9 CPU, memory and drop figures; results for SC-11 and the SC-10 24-hour soak |
| Developer docs (`README.md`, `docs/`) | Whoever continues the code | Build, test and run on `vcan0`; pinned dependencies; this hand-off, requirements, log format, errors table and threat model; LICENSE (MIT) |
| Transition overview (`docs/transition.md`) | The recipient | Outline below |
| Porting guide (`docs/porting.md`) | Whoever moves the logger to other hardware | Outline below |
| Release notes (`CHANGELOG.md`) and `LICENSE` | The recipient | Changes in each tagged release; MIT License |
| Review record (`docs/reviews.md`) | Instructor, the recipient | One line per build step: date, reviewer, what was checked, issues found |
| Findings report (`docs/findings.md`) | ORNL, instructor, whoever continues | The validation report (X30), to `docs/findings-report-spec.md`; data in `docs/findings-data/` |
| Error-handling table (`docs/errors.md`) | Developers; source of the troubleshooting table | Every expected error: source, detection, logger action, record, light, transmit state, test (X36) |
| No-hardware demo (`demo/run_demo.sh`) | The recipient | Runs the logger and laptop tool on `vcan0` against the session 142 scenario (X31) |
| Recorded walkthrough (optional) | The recipient | 15 to 20 minutes: demo, install, training, a new device, retrieval and report, porting (X34) |

**User manual outline.** Each task section gives when to do it, the steps, example screen output, and what can go wrong.

1. **Getting started:** what the logger does (what it records, what it sends, what it never does, where the data goes); what you need; running the no-hardware demo (a Linux machine or VM); setting up the Windows laptop (Python, `j1939ctl`, OpenSSH, an SSH key with a passphrase) and connecting it (the logger's fixed address and DHCP), then a first `status`; installing the logger (tap, stub length, termination off, mount and label, connector and network settings, the VIN request address `requests.vin_sa`, bus error counts before and after).
2. **Everyday use:** the status light and the `status` screen; training a truck (the 7-step procedure, PTO from PTO1 or declared, `train status`, `train finish`; safety: a driver plus a separate laptop operator, and never use the laptop while driving); reviewing new events (approve, clear or escalate, with examples); changing the inventory (approve or remove a device or PGN); retrieving logs and running the report (back up retrieved folders and store them under the agreed data-handling rules); reading the report (the five sections and the `events.csv` columns); changing a setting (a plain-language settings table and the detection-weakening warning).
3. **Less common tasks:** restart or retrain; moving the logger to another truck by hand (retrieve, verify, archive the folder, `retrain`, new connector and network settings); replacing the card or removing the logger (retrieve first, power down, check that the gap is flagged; the card is ext4, so card-swap retrieval needs a Linux machine or VM).
4. **For analysts:** the files on the card and the session file layout (full schema in `log-format.md`); the chain check and what to do if it fails; opening raw captures with can-utils or SavvyCAN.
5. **Admin:** logging in, file locations, starting and stopping the service, the diagnostic log; installing from the release bundle with install.sh, updating by installing a newer release and rolling back by installing the previous one; adding and removing operator keys, including a lost laptop; the hardening checklist and the Beacon procedure; updating the device library (characterize the device on the bench, add an entry with its function codes, PGNs and optional make and model, raise the library version, install it with the release); deleting data by hand.
6. **Reference:** troubleshooting table, generated from `docs/errors.md` (no bit rate, transmit off, card nearly full or full, clock invalid, VIN mismatch, cannot connect, chain check failed, logger not starting); command reference (16 commands with examples); glossary (NAME, source address, PGN, ECU, DM, VIN, inventory, session, event ID); FAQ; escalation contact.

**Appendix, printable quick card:** the light patterns, the five most-used commands, the new-event decision guide and the contact line, on one page.

**Transition overview outline** (`docs/transition.md`, 2 to 3 pages).

1. **What it does and its status** *(at hand-over)*: a prototype; the cut-line tier reached (X13) and whether it was proven on the Beacon or handed over under the vcan fallback (X12).
2. **What was verified and where:** a summary of `docs/verification.md`, the tier reached, each gap and its reason, the SC-9 figures, and a pointer to the findings report.
3. **Core profile:** the Demo subset, and what can be ignored. "Out of scope for this prototype, including timing and cadence fingerprinting: see requirements, Not required."
4. **What you must obtain:** the SAE J1939 Digital Annex, a manufacturer code list you are licensed to use, the J1939 standards cited, hardware that meets PLT-1 to PLT-8 (see the buying guide in `docs/porting.md`), and the minimum acceptance setup; "A Linux machine or VM for the no-hardware demo; a Windows laptop with Python 3 and OpenSSH for the operator tool."
5. **Getting started:** the no-hardware demo, then the user manual and the porting guide.
6. **Known limits:** from the requirements, quoted as written there, including: "Logs on a removed microSD card are readable and not encrypted. They are hash-chained but not signed (LOG-24 deferred), so someone holding the card could rewrite records not yet retrieved and recompute the chain" and "Operators have a shell on the logger (STS-21 deferred); their tool actions are logged, but direct file edits are not."
7. **Decisions left to you:** retrieval schedule and reviewer (STS-8), escalation contact, and data handling and retention.
8. **Licence and support:** MIT. No support continues after the semester; the user manual, troubleshooting table and decision log are the only references.

**Porting guide outline** (`docs/porting.md`): a hardware buying guide and the backup platform (X21, X37); the platform functions and what each must do (`open_can(listen_only)`, `bitrate_check()`, `set_light(pattern)`, `now()`, `rtc_ok()`, `on_wake()`, `watchdog_kick()`, `paths()`); the desktop and Beacon implementations as references; the steps to port; the minimum acceptance setup (X20); acceptance tests A1 to A8 and how to record their results.

## Ground rules (CLAUDE.md)

The repository's `CLAUDE.md` carries these rules and points to `docs/`.

1. Read `docs/handoff.md`, then `docs/requirements.md` and `docs/log-format.md`, before changing code.
2. Work one build step at a time. A step is done only when its tests pass (with ruff and mypy) and its demo runs on `vcan0`.
3. Every test name starts with the requirement ID it verifies (tooling tests: the DC ID that defines the tool, DC-6). Every requirement marked T, except those marked Deferred, gets at least one test.
4. All bus transmission goes through `transmit`. Never add a PGN to the transmit allow-list, never send a command, clear or write, never resume transmitting in a session after NP-18 turns it off, and never raise the rate cap. If a task seems to need one, stop and ask.
5. Keep `capture` behind its interface; nothing else touches the CAN socket for receiving. Use raw CAN sockets; J1939 address claiming and transport protocol are handled in this code.
6. Log records must match `docs/log-format.md` exactly. A new field or record type means updating that spec first, raising its format version and adding a format history line, then the code.
7. Defaults live in the config file, not in code. Keys live on internal flash, never on the card. Build nothing marked Deferred.
8. Never delete event files (wipe, STS-14, is deferred), and never write to a session file except by appending.
9. If documents disagree, the requirements win, and the log format wins on any field or record detail; apply that and report the disagreement.
10. Use only what the requirements call for; anything in "Not required" stays out.
11. Keep the user manual's command reference and troubleshooting table in step with the tool: a change to a command, message or fault updates the manual in the same change; the troubleshooting table is generated from `docs/errors.md`.
12. Only `platform/` may contain hardware- or Beacon-specific code. Everything else reaches the hardware through its interface, so all tests run on the desktop implementation.
13. Ship no licensed content: no SAE Digital Annex tables and no manufacturer code list in the repository; the list in `data/` stays empty.
14. Errors: catch broadly only at the top of each thread; logging or status failures never crash the logger; log a repeated error once, with a count; take time only from the platform layer; after a crash, rebuild the last hash from the last complete line of the newest session file. Every expected error has a row in `docs/errors.md` and a test.
15. Only the logger service writes the session file, inventory, config, status file and `state.json`; inside it, only `eventlog` writes session files and only `store` writes supporting files. Laptop commands reach it through `j1939cmd` and the Unix socket (STS-23).
16. Build to the contracts in `docs/modules.md`. Anything that departs from a contract, a requirement, the log format or the error table needs an entry in `docs/design-changes.md` first. You may write it as proposed, but do not build on it until a project member marks it accepted; change the affected specs in the same pull request, and raise the contract version.
17. Every pull request uses `.github/pull_request_template.md`: it is the definition of done. Work on one branch per build step or module, claim it in the pull request title, and end the description with the state block so the next session can pick up.

## Open checks and what to stub

These are unresolved, but none blocks steps 1 to 7 on a desktop. Build behind the platform interface and stub in its desktop implementation. They are checked on the unit in build step 2a (go/no-go, decisions X18 and X41); hardware tests follow in step 8. If SocketCAN or listen-only fails on the Beacon, the hardware tier switches to the backup platform (X21); the vcan fallback (X12) applies only if that also fails, with each gap recorded in verification.md and the transition overview.

| Item | Blocks | Until resolved |
| --- | --- | --- |
| Kernel J1939 support on the Beacon | Step 3 on the Beacon | Use raw CAN sockets with `decode` handling J1939, which works on any kernel. Decided default; kernel J1939 is an optional optimization |
| SocketCAN interfaces and transmit on the Beacon | Step 8 | Desktop `vcan0` only |
| Python 3 and pip packages on the Beacon | Step 8 | Desktop only; keep run-time dependencies to the standard library (python-can is an optional extra, X22) |
| Listen-only mode on the Beacon | NP-1 on hardware | `capture` exposes a mode setting; on `vcan0` it is a no-op |
| Real-time clock | LOG-16 on hardware | `clock` reads an injectable source |
| Sleep and wake on CAN; boot and wake-to-ready time | HW-5, HW-8 | `session` takes wake events from `platform`; measure wake-to-ready time on the bench (sleep is future research, X39) |
| Controllable status LEDs | STS-1 on hardware | `status` writes the status file; lights behind an interface |
| Custom systemd service | Step 8 | Run from the command line |
| Control and DM PGN numbers | DET-9, DET-10 | Closed Nov 7: the numbers in config were checked; confirm once against J1939-71 and J1939-73 when the standards are available |
| New PGN from known or approved devices (ORNL check) | DET-12 | Build it behind the `detection.known_device_new_pgn` switch, default on |
| Retrieval schedule and reviewer (ORNL) | STS-8 | Not a software item |
| Stub limits at 500 kbit/s | HW-1 | Not a software item |
| Trailer devices on the tractor's J1939 bus; NAME vehicle system value for a trailer | DET-18 | Read the value from config (`classify.trailer_vehicle_system`, default 2); correct it in config once verified against J1939 Appendix B. Whether trailer devices appear at the 9-pin port is checked on fleet trucks, not a software item |
| Writable internal flash and systemd watchdog on the Beacon | LOG-22, STS-18 on hardware | Watchdog behind an interface, tested with a stub on the desktop (the internal flash fallback is deferred) |
| Beacon accounts, services and radios | STS-20 on hardware | Hardening is an install checklist; seals and release signatures are deferred, so nothing is built for them |
| Escalation contact and data-handling rules (ORNL) | User manual | Leave a marked placeholder in the manual and on the quick card |

## Future work (do not build)

- **Fleet profiles:** merged inventories for trucks of the same configuration, so a new truck needs only a short training. Keep the inventory format ready for them: vehicle configuration fields, and trained PGNs separate from later approvals (TRN-13).
- **Onboard screen:** a display on the logger for training, approvals and review in place of the laptop. Keep the command logic in `admin` and `inventory`, not in `j1939ctl`, so a screen can call the same functions later.
- **ISO 15765:** diagnostics over CAN, decoding only.
- **Forced command per operator key** (X24): operator keys run only `j1939cmd`, with no shell, alongside deferred STS-21.
- **Low-power sleep** (X39): no battery drain over about 3 months parked; needs a power controller that wakes on CAN or ignition (HW-5, PLT-4).
- **Two-person approval:** a second operator to confirm control-PGN approvals and removal of trained ECUs.
- **Deferred requirements:** everything marked Deferred in the requirements (HW-5, PLT-4, LOG-21, LOG-24, IDN-7, STS-13 to STS-16, the STS-17 migration, STS-21, STS-22, LAP-16, SC-12 except SC-12a) and the deferred parts of SC-10, STS-10, STS-18, STS-20, LOG-22, LAP-1, LAP-15 and the DET-19 flood record. Do not build these.
