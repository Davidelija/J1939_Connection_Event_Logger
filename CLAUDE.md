# J1939 connected-devices event logger

This repository builds a logger that sits on a heavy truck's 9-pin J1939 diagnostic connector, learns the vehicle's known-good devices, and logs every new device that connects (ELDs, scan tools, anything else) in a hash-chained event log. The prototype runs on a DG Technologies Beacon; development and tests run on desktop Linux against `vcan0`. All hardware-specific code lives in `src/j1939logger/platform/`, so the logger can move to other hardware (`docs/porting.md`).

## Read first

1. `docs/handoff.md`: decisions, repository layout, modules, build plan, testing, open checks.
2. `docs/requirements.md`: every requirement with its ID, verification method and status.
3. `docs/log-format.md`: the authoritative schema for every file the logger writes.
4. `docs/examples/`: one worked session (session 142) showing every file type. The hash chain in the session file verifies.
5. `docs/transition.md` and `docs/porting.md`: written for the recipient; keep them current as the build progresses.
6. `docs/errors.md`: every expected error and how the logger handles it.
7. Background, read as needed: `docs/background/` (Beacon doc, detection doc, architecture page).
8. `docs/modules.md`: each module's contract (inputs, outputs, errors, test seam), the shared types, layering and the freeze table.
9. `docs/design-changes.md`: every design change since the Nov 10 baseline. Read it at the start of every session.

If these documents disagree, the requirements win, then `docs/log-format.md` on any field or record detail, then `docs/modules.md` on module boundaries, then the hand-off. Report any disagreement; do not resolve it silently.

## Ground rules

1. Read the documents above before changing code.
2. Work one build step at a time, in the order in `docs/handoff.md`. A step is done when every item in the pull request template is ticked (rule 17).
3. Every test name starts with the requirement ID it verifies, for example `test_NP_14_request_timeout_and_retry`. Every requirement marked T, except those marked Deferred, gets at least one test; keep `docs/verification.md` current. CI fails if a T requirement that is not Deferred has no test once its build step (the Step column) has merged; for step 8 requirements a `bench/` procedure ID counts (DC-2). The test plan is `docs/test-plan.md`.
4. All bus transmission goes through the `transmit` module. Never add a PGN to the transmit allow-list, never send a command, clear or write, never resume transmitting in a session after NP-18 turns it off, and never raise the rate cap (10 frames/s, one outstanding request per destination). If a task seems to need one, stop and ask.
5. Use raw CAN sockets; J1939 (address claiming, transport protocol) is handled in this code. Kernel J1939 sockets are an optional later optimization.
6. Keep `capture` behind its interface (frames in, timestamped records out); nothing else touches the CAN socket for receiving.
7. Log records must match `docs/log-format.md` exactly, including the hash serialization rule. A new field or record type means updating that spec first, raising its format version and adding a format history line, then the code.
8. Defaults live in the config file, not in code. Keys live on internal flash, never on the card.
9. Never delete event files (`wipe`, STS-14, is deferred), and never write to a session file except by appending.
10. Use only what the requirements call for; anything under "Not required (out of scope)" or "Future work", or marked Deferred, stays out.
11. Keep `docs/user-manual.md` in step with the tool: a change to a command, message or fault updates the manual's command reference and troubleshooting table in the same change; the troubleshooting table is generated from `docs/errors.md`.
12. Only `platform/` may contain hardware- or Beacon-specific code. Everything else reaches the hardware through its interface, so all tests run on the desktop implementation.
13. Ship no licensed content: no SAE Digital Annex tables and no manufacturer code list in the repository; the list in `data/` stays empty.
14. Errors: catch broadly only at the top of each thread; logging or status failures never crash the logger; log a repeated error once, with a count; take time only from the platform layer; after a crash, rebuild the last hash from the last complete line of the newest session file. Every expected error has a row in `docs/errors.md` and a test.
15. Only the logger service writes the session file, inventory, config, status file and `state.json`; inside it, only `eventlog` writes session files and only `store` writes supporting files. Laptop commands reach it through `j1939cmd` and the Unix socket (STS-23).
16. Build to the contracts in `docs/modules.md`. Anything that departs from a contract, a requirement, the log format or the error table needs an entry in `docs/design-changes.md` first. You may write it as proposed, but do not build on it until a project member (Vaughan Lynn or Elijah Umaru) marks it accepted; change the affected specs in the same pull request, and raise the contract version.
17. Every pull request uses `.github/pull_request_template.md`: it is the definition of done. Work on one branch per build step or module, claim it in the pull request title, and end the description with the state block so the next session can pick up.

## Environment

- Python 3 with the standard library at run time; `python-can` only as an optional extra in the platform layer; dev tools `pytest`, `hypothesis`, `ruff`, `mypy`, `pytest-cov`, `import-linter` (layering check, `docs/modules.md` §2) and `python-can` (test harness only: the witness and `ecu_sim`; `src/` imports it only in `platform/`); all pinned by version and hash. The laptop tool targets Windows. Keep other dependencies to the standard library.
- Tests load the `vcan` kernel module and use `canplayer` and `candump` from can-utils.
- Hardware-only checks live in `bench/` as written procedures, not automated tests: platform-neutral acceptance tests A1 to A8, the B-procedures (B-HW1, B-HW3, B-PLT2, B-STS20, B-SN1) and `bench/checklists.md` for every D, I and A requirement. Test levels and folders are in `docs/test-plan.md` §2.
- The code is provided under the MIT License (`LICENSE`).
- `demo/run_demo.sh` is the no-hardware demo and runs in CI as an end-to-end smoke test.
- From Tuesday, Nov 10, 2026, `docs/` is the only copy of the specs; edit them here (decision X19).
