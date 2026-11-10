# Module test matrix

Which test levels each module gets, built from the test seams in `docs/modules.md` §4 and the levels in §5. Companion to `docs/test-plan.md` (version 2, Nov 9, 2026). Layer and freeze step are from `docs/modules.md` §2 and §6.

| Function | Module | Layer | Frozen before step | Unit | Contract | Malformed input | Component | Fault plan | Replay / end to end | Rig | Validation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bus input and output | `capture` | 1 | 1 | ● | ● |  | ● | ● | ● | ● |  |
| Bus input and output | `decode` | 2 | 1 | ● | ● | ● | ● | ● | ● |  |  |
| Bus input and output | `transmit` | 1 | 3 | ● | ● |  | ● | ● | ● | ● |  |
| Bus input and output | `address` | 3 | 3 | ● | ● |  | ● |  | ● | ● |  |
| Bus input and output | `requests` | 3 | 3 | ● | ● |  | ● |  | ● |  |  |
| Detection and identification | `detect` | 3 | 4 | ● | ● |  | ● |  | ● | ● | ● |
| Detection and identification | `monitor` | 3 | 4 | ● | ● | ● | ● |  |  | ● |  |
| Detection and identification | `identify` | 3 | 5 | ● | ● |  | ● |  | ● | ● | ● |
| Detection and identification | `inventory` | 3 | 6 | ● | ● |  | ● |  | ● |  |  |
| Recording and storage | `eventlog` | 1 | 1-2 | ● | ● |  | ● | ● | ● | ● |  |
| Recording and storage | `store` | 1 | 2 | ● | ● |  | ● | ● |  | ● |  |
| Recording and storage | `rawcap` | 1 | 6 | ● | ● |  | ● |  |  |  |  |
| Recording and storage | `retention` | 3 | 6 | ● | ● |  | ● | ● |  |  |  |
| Recording and storage | `clock` | 1 | 1 | ● | ● |  | ● | ● |  | ● |  |
| Status, configuration and admin | `status` | 3 | 7 | ● | ● |  | ● |  |  | ● |  |
| Status, configuration and admin | `config` | 2 | 2 | ● | ● |  | ● |  | ● |  |  |
| Status, configuration and admin | `session` | 4 | 2 |  | ● |  | ● | ● | ● | ● |  |
| Status, configuration and admin | `admin` | 4 | 7 |  | ● |  | ● |  | ● |  |  |
| Status, configuration and admin | `cmdserver` | 5 | 7 | ● | ● |  | ● | ● | ● |  |  |
| Status, configuration and admin | `j1939cmd` | 5 | 7 |  | ● |  |  |  | ● |  |  |
| Hardware boundary | `platform` | 0 | 1 | ● | ● |  | ● | ● | ● | ● |  |
| Laptop and standalone tools | `j1939ctl` | laptop | 7 |  | ● |  |  | ● | ● | ● |  |
| Laptop and standalone tools | `verify_chain` | tool | 2 | ● | ● |  |  |  | ● |  |  |

## How each level is evaluated

| Level | What it is | How it is evaluated |
| --- | --- | --- |
| Unit | Level 1: a module's public functions, pytest | Pass/fail in CI on every push; exact outputs and known answers (session 142 hashes, IDN-4 scores); ruff and mypy must pass. |
| Contract | mypy against the module's Protocol; public-names import test; import-linter layers | Pass/fail in CI: the implementation matches its Protocol, imports only public names, and respects the layers in docs/modules.md section 2. |
| Malformed input | Hypothesis property tests (SC-12a) | No unhandled exception, keeps decoding, within DET-19 limits, counts match. Fixed seed in CI, random nightly; failures kept as regression cases. |
| Component | Level 2: session in-process with DesktopPlatform and FakeClock, fed from a fixture folder | Manifest matching (type, sev, listed fields; within_s; count 0; expect_no_other) and verify_chain over every session file written. |
| Fault plan | DesktopPlatform fault plan with kinds from docs/errors.md (levels 2 and 3) | The row's Action, Record, Light and Transmit columns all match; one test per errors.md row. |
| Replay / end to end | Level 3: service on vcan0, witness, ecu_sim, j1939cmd over ssh localhost | Manifest matching; witness sees only allow-listed frames within 10 frames/s; command records, refusals and exit codes correct. |
| Rig | Level 4: bench procedures A1 to A8, SC-9/10/11, B-procedures, manual LAP-1 | Each procedure's pass criterion; result, date, platform and evidence recorded in docs/verification.md. |
| Validation | Scored scenario runs (tools/findings) | Not pass/fail: measured detection and identification performance, every number produced by script. |

Notes: inventory file round-trips are `store` tests; inventory and library validation are `config` tests. `session`, `admin`, `j1939cmd` and `j1939ctl` have no level 1 tests of their own; their contracts name levels 2 and 3 as their seams. Developers own level 1 and contract tests; test-script writers own fixtures, the component runner, replay tests, bench procedures and findings scripts (`docs/test-plan.md` §3).
