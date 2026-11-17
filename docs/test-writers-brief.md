# Brief for the test-script writers: levels 2 and 3

Written by the developers on 2026-11-16, after build step 7 and the QC-3 fixes. It hands over what the test plan's component and replay levels need. The plan itself is `docs/test-plan.md`; this brief says what exists today, what is missing and where to start.

## Who owns what

DC-4 gives these to the test-script writers: `tests/component/`, `tests/replay/`, `tests/harness/`, `tests/fixtures/`, `tools/fixtures/`, `bench/` and `tools/findings/`. Developers do not write in them. A change on the other side's area (for example a new hook in `src/`) goes through a DC entry in `docs/design-changes.md`.

Until `tests/component/` exists, **DC-24** counts the developers' in-process session tests (`tests/unit/test_session_*.py`) as level 2 evidence. When your component tests land, tell the developers: they remove the DC-24 notes from `docs/test-plan.md` §2 and `docs/verification.md`.

## What exists that you can build on

| Piece | Where | Use |
| --- | --- | --- |
| Fake time | `FakeClock` in `src/j1939logger/platform/desktop.py` | `advance(s)`, `jump(s)`; runs 24 h in one call |
| Fault injection | `DesktopPlatform(fault_plan=[(at_mono, kind, args)])` | Kinds are the Kind column of `docs/errors.md`; `args` take `for_s` and `ops` (see the module docstring) |
| The logger in-process | `Session(platform, settings, inventory, versions, startup_faults)`; `start()`, `step()`, `stop()`, `run()` | Feed frames with `session.capture._ingest(frame)`; this is the level 2 entry point |
| The logger as a service | `python -m j1939logger.main --root DIR --config FILE --inventory FILE --socket PATH --interface vcan0` | Level 3: a temporary card and flash under `--root` |
| Commands | the `cmdserver` socket (level 2); `j1939cmd` (level 3); `j1939ctl` with a transport (see `tests/unit/test_j1939ctl.py`'s `Local`) | |
| Chain check | `tools/verify_chain.py` (`verify([folders], last_hash=...)`, CLI with `--json`) | For `records.py` |
| Smoke test | `demo/run_demo.sh` | Shows a replay with `canplayer` on `vcan0` |
| Frame builders | `tests/unit/test_session_transmit.py` (`frame`, `bam_frames`, `RecordingSocket`), `tests/unit/test_session_identify.py` (`claim`, `request`) | Copy them into `tests/harness/frames.py`; don't import from `tests/unit/` |
| Malformed input | `tests/malformed/` with a nightly random seed and `tests/malformed/regressions/` | Already covers SC-12a for `decode` and `monitor` |
| Examples | `docs/examples/` (session 142, `cfg-v3.json`, `inv-v2.json`, `lib-v1.json`) | Starting point for fixtures |

CI (`.github/workflows/ci.yml`) already loads `vcan`, brings up `vcan0` and installs can-utils, so replay tests run in CI with no workflow change. Python is 3.9 until step 2a confirms the Beacon's version.

## What is missing, in the order to build it

1. **`tests/harness/`** (test plan §3): `witness.py`, `ecu_sim.py`, `logger_proc.py`, `records.py`, `frames.py`. Everything else depends on them.
2. **`tools/fixtures/scenario.py`** and the first **`tests/fixtures/<scenario>/`** folders (`traffic.log` in candump `-L` format, `manifest.json` with `expect` entries).
3. **`tests/component/`** and its fixture runner: the component-level COM cases, then the DID detection and identification scenarios (19), then the SN state-file cases (7).
4. **`tests/replay/`**: the replay-level COM cases (with `ecu_sim` and the witness), then the ATK cases (6). Every replay test also checks the transmit statement (test plan §5).
5. **BEN** (4) and the A-procedures run on the rig in step 8 (`bench/`).

## Coverage today, by case

- **COM-01 to COM-17:** `docs/test-plan.md` §5, "Coverage today (DC-24)", lists the level 2 and level 1 tests for each case and what still needs replay or the rig. Every case except COM-15 and COM-16 (rig only) has a session-level test; none has a replay test.
- **DID (19), ATK (6), BEN (4):** no test carries these case IDs yet.
- **SN-a to SN-f (7):** `test_LOG_5_SN_b_*` and `test_LOG_5_SN_d2_*` name their cases; the other five are exercised by `test_LOG_5_*` tests in `tests/unit/test_session_lifecycle.py` without the case ID.

## Conventions

- Every test name starts with the requirement ID it verifies (`test_NP_14_...`, CLAUDE.md rule 3), and `docs/verification.md` names tests in full, one per clause for the safety-critical rows.
- The test plan asks tests to carry their case IDs (COM-, DID-, SN-, ATK-, BEN-). There is no convention for it yet. pytest runs with `--strict-markers`, so a `case` marker needs an entry in `pyproject.toml`; agree the convention with the developers first.
- Pull requests use `.github/pull_request_template.md`, one branch per piece of work, and a line in `docs/reviews.md`.
- `transmit.py`, `config.py`, `eventlog.py`, `platform/`, `session/can.py`, `session/core.py`, `capture.py`, `tests/contract/` and `.github/CODEOWNERS` are safety-critical (DC-25): changes there need a review by Vaughan Lynn or Elijah Umaru.

## Known traps

- Windows checkouts with long paths: set `git config core.longpaths true`; keep new file names short.
- Tests that need `vcan0` skip on Windows and on Linux without it; CI has it.
- The session's high-fault state now follows any high fault, even one that cannot be written (QC-3 R2); a storage outage gives one fault record with a count (rule 14). Write `expect` entries for those, not one fault per failed write.
