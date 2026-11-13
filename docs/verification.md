# Verification matrix

One row per requirement in `docs/requirements.md`. Update the rows a build step touches at the end of that step (hand-off build plan); Beacon go/no-go results from step 2a are recorded here too.

- **Step:** the build step whose merge makes the row required by the coverage check (DC-2); for requirements verified by D, I or A only, the step in `bench/checklists.md`; — for Deferred rows.
- **Test or procedure:** the test name (it starts with the requirement ID) or the `bench/` procedure and step.
- **Where:** vcan, Beacon, backup platform, or not verified.
- **Result:** pass, fail, or not supported on the Beacon, with the reason.
- **Evidence:** the CI run, test report section or results file.

The goal is a Beacon result for every hardware-relevant T requirement. If a Beacon check fails or time runs out, the vcan build is handed over and each gap is recorded here (Where: not verified, or Result: not supported on the Beacon, with the reason) and summarized in `docs/transition.md` §2 (decisions X9, X12).

A CI check (`tools/check_verification.py`, staged by DC-2) fails if a requirement marked T has no test once its Step has merged, skipping Deferred rows. For step 8 requirements, a `bench/` procedure ID in the Test-or-procedure column satisfies the check. Before a release tag the check requires every T row to have a passing test, a procedure with a result, or a recorded gap.

**Merged build steps:** none. *(The pull request that completes a build step adds it here; `tools/check_verification.py` reads this line.)*

| ID | Method | Step | Test or procedure | Where | Result | Date | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SC-1 | I, T | 8 |  |  |  |  |  |
| SC-2 | T | 3 | `test_SC_2_read_batch_never_waits_and_keeps_order` | vcan | partial: capture reading side; bit-rate confirmation in step 3 | 2026-11-13 | CI, PR step-1-logic |
| SC-3 | T | 5 |  |  |  |  |  |
| SC-4 | T | 8 |  |  |  |  |  |
| SC-5 | D | 8 |  |  |  |  |  |
| SC-6 | I, A | 9 | `tests/contract/` (`test_SC_6_*`), import-linter layers contract | vcan | partial: platform Protocol conformance, public names and layering in CI; inspection and analysis in step 9 | 2026-11-13 | CI, PR step-1-interfaces |
| SC-8 | D | 2 |  |  |  |  |  |
| SC-9 | T | 8 |  |  |  |  |  |
| SC-10 | T | 8 |  |  |  |  |  |
| SC-11 | T | 8 |  |  |  |  |  |
| SC-12 | T | — | Deferred, not built |  |  |  |  |
| SC-12a | T | 1 | `test_SC_12a_*` (tests/malformed) | vcan | partial: decode under Hypothesis; monitor joins in step 4 | 2026-11-13 | CI, PR step-1-logic |
| NP-1 | T | 3 |  |  |  |  |  |
| NP-2 | T | 3 |  |  |  |  |  |
| NP-3 | T | 3 |  |  |  |  |  |
| NP-4 | T | 3 |  |  |  |  |  |
| NP-5 | I, T | 3 |  |  |  |  |  |
| NP-6 | T | 3 |  |  |  |  |  |
| NP-7 | T | 3 |  |  |  |  |  |
| NP-8 | T | 3 |  |  |  |  |  |
| NP-9 | T | 3 | `test_NP_9_oversize_rts_to_logger_gets_connection_abort` | vcan | partial: decode asks for Connection Abort; transmit in step 3 | 2026-11-13 | CI, PR step-1-logic |
| NP-11 | T | 3 |  |  |  |  |  |
| NP-12 | T | 3 |  |  |  |  |  |
| NP-13 | T | 3 |  |  |  |  |  |
| NP-14 | T | 3 |  |  |  |  |  |
| NP-15 | T | 3 | `test_NP_15_own_frames_and_replies_to_logger_are_marked` | vcan | partial: decode marks own frames and replies; exclusion from detection in step 4 | 2026-11-13 | CI, PR step-1-logic |
| NP-16 | T | 3 |  |  |  |  |  |
| NP-17 | T | 3 | `test_NP_17_no_bitrate_fault_gives_none_while_active`, `test_NP_17_can_missing_fault_raises_platform_error`, `test_NP_17_missing_interface_raises_can_missing`, `test_NP_17_interface_down_raises_can_down_from_read_batch`, `test_NP_17_can_down_fault_plan_reaches_read_batch`, `test_NP_17_missing_interface_raises_can_missing_on_start` | vcan | partial: desktop platform fault injection only; logger behaviour in step 3; capture raises can_missing and can_down | 2026-11-13 | CI, PR step-1-logic |
| NP-18 | T | 3 |  |  |  |  |  |
| NP-19 | T | 3 |  |  |  |  |  |
| TRN-2 | D | 6 / 8 |  |  |  |  |  |
| TRN-3 | T | 6 |  |  |  |  |  |
| TRN-4 | D | 7 |  |  |  |  |  |
| TRN-5 | D | 7 |  |  |  |  |  |
| TRN-6 | I | 6 |  |  |  |  |  |
| TRN-7 | I | 6 |  |  |  |  |  |
| TRN-9 | T | 6 |  |  |  |  |  |
| TRN-10 | T | 6 |  |  |  |  |  |
| TRN-11 | T | 6 |  |  |  |  |  |
| TRN-12 | T | 6 |  |  |  |  |  |
| TRN-13 | I | 6 |  |  |  |  |  |
| TRN-14 | T | 6 |  |  |  |  |  |
| TRN-15 | T | 6 |  |  |  |  |  |
| DET-1 | T | 1 |  |  |  |  |  |
| DET-2 | T | 4 |  |  |  |  |  |
| DET-3 | T | 4 |  |  |  |  |  |
| DET-4 | T | 4 |  |  |  |  |  |
| DET-5 | T | 4 |  |  |  |  |  |
| DET-6 | T | 4 |  |  |  |  |  |
| DET-7 | T | 4 |  |  |  |  |  |
| DET-8 | T | 4 |  |  |  |  |  |
| DET-9 | T | 4 |  |  |  |  |  |
| DET-10 | T | 4 | `test_DET_10_etp_is_recognized_and_counted_not_reassembled` | vcan | partial: decode recognizes ETP; connection records in step 4 | 2026-11-13 | CI, PR step-1-logic |
| DET-11 | T | 4 |  |  |  |  |  |
| DET-12 | T | 4 |  |  |  |  |  |
| DET-13 | T, A | 5 |  |  |  |  |  |
| DET-14 | T | 6 |  |  |  |  |  |
| DET-15 | T | 4 |  |  |  |  |  |
| DET-16 | T | 1 |  |  |  |  |  |
| DET-17 | T | 4 |  |  |  |  |  |
| DET-18 | T | 5 |  |  |  |  |  |
| DET-19 | T | 1 | `test_DET_19_*` | vcan | partial: decode limits (open transfers, 1785 bytes, T1 to T4, non-J1939 counts, malformed counts); pgns_per_conn in step 4, raw_mb_per_session in step 6 | 2026-11-13 | CI, PR step-1-logic |
| IDN-1 | T | 1 | `test_IDN_1_*` | vcan | pass: NAME fields decoded as raw numbers (logger NAME, session 142 scan tool) | 2026-11-13 | CI, PR step-1-logic |
| IDN-2 | I | 5 |  |  |  |  |  |
| IDN-3 | T, A | 5 |  |  |  |  |  |
| IDN-4 | T, A | 5 |  |  |  |  |  |
| IDN-5 | D | 5 / 8 |  |  |  |  |  |
| IDN-6 | T | 5 |  |  |  |  |  |
| IDN-7 | T | — | Deferred, not built |  |  |  |  |
| LOG-1 | I | 2 |  |  |  |  |  |
| LOG-2 | T | 2 |  |  |  |  |  |
| LOG-3 | I, T | 2 | `test_LOG_3_*` | vcan | partial: one write() per record, O_APPEND, sync_now(); periodic sync thread in step 2 | 2026-11-13 | CI, PR step-1-logic |
| LOG-4 | I | 1 | `test_LOG_4_*` | vcan | partial: common fields, key order and time formats written by eventlog; veh_time and elapsed-mode utc in step 2 | 2026-11-13 | CI, PR step-1-logic |
| LOG-5 | T | 1 | `test_LOG_5_*` | vcan | partial: hash rule (every session 142 hash reproduced) and chain within a file; chain across sessions and state.json in step 2 | 2026-11-13 | CI, PR step-1-logic |
| LOG-6 | I | 2 |  |  |  |  |  |
| LOG-7 | T | 4 |  |  |  |  |  |
| LOG-8 | I | 7 |  |  |  |  |  |
| LOG-9 | T | 3 |  |  |  |  |  |
| LOG-10 | T | 6 | `test_LOG_10_ring_keeps_raw_before_s_plus_2_seconds`, `test_LOG_10_window_includes_both_ends` | vcan | partial: capture ring and window; rawcap in step 6 | 2026-11-13 | CI, PR step-1-logic |
| LOG-11 | T | 6 |  |  |  |  |  |
| LOG-12 | T | 2 |  |  |  |  |  |
| LOG-13 | I | 2 |  |  |  |  |  |
| LOG-14 | T | 2 |  |  |  |  |  |
| LOG-15 | T | 2 | `test_LOG_15_*` | vcan | partial: capture stats (buffer read back, kernel drops, frames by type) and kernel timestamps; session_start and session_end fields in step 2 | 2026-11-13 | CI, PR step-1-logic |
| LOG-16 | T | 2 | `test_LOG_16_fakeclock_*`, `test_LOG_16_now_reads_the_fake_clock`, `test_LOG_16_rtc_invalid_*`, `test_LOG_16_clock_jump_*`, `test_LOG_16_host_clock_used_without_fake_clock`, `test_LOG_16_parse_time_date`, `test_LOG_16_rtc_source_*`, `test_LOG_16_elapsed_*`, `test_LOG_16_never_waits_*`, `test_LOG_16_vehicle_time_*`, `test_LOG_16_first_time_date_*`, `test_LOG_16_skew_*`, `test_LOG_16_clock_jump_does_not_move_monotonic_timers`, `test_LOG_16_own_and_other_pgns_ignored` | vcan | partial: FakeClock and desktop `now()`/`rtc_ok()` only; `clock` module tests come with step 1 PR 2; clock module: source choice, vehicle offset, skew fault, jumps | 2026-11-13 | CI, PR step-1-logic |
| LOG-17 | T | 2 |  |  |  |  |  |
| LOG-18 | T | 2 |  |  |  |  |  |
| LOG-19 | T, I | 2 |  |  |  |  |  |
| LOG-20 | T | 2 |  |  |  |  |  |
| LOG-21 | T | — | Deferred, not built |  |  |  |  |
| LOG-22 | T | 6 | `test_LOG_22_*` | vcan | partial: platform fault(op) and eventlog storage faults; reserve and card-full handling in step 6 | 2026-11-13 | CI, PR step-1-logic |
| LOG-23 | T | 2 |  |  |  |  |  |
| LOG-24 | T | — | Deferred, not built |  |  |  |  |
| STS-1 | D | 8 | `test_STS_1_set_light_*` | vcan | partial: desktop `set_light()` patterns only; light priority in step 7, A8 in step 8 | 2026-11-13 | CI, PR step-1-interfaces |
| STS-2 | D | 7 / 8 |  |  |  |  |  |
| STS-3 | I | 7 |  |  |  |  |  |
| STS-4 | I, D | 8 |  |  |  |  |  |
| STS-5 | D | 7 / 8 |  |  |  |  |  |
| STS-7 | D | 7 |  |  |  |  |  |
| STS-8 | I | 9 |  |  |  |  |  |
| STS-9 | T | 7 |  |  |  |  |  |
| STS-10 | T | — | Deferred, not built |  |  |  |  |
| STS-11 | T | 7 |  |  |  |  |  |
| STS-12 | T | 7 |  |  |  |  |  |
| STS-13 | T | — | Deferred, not built |  |  |  |  |
| STS-14 | T | — | Deferred, not built |  |  |  |  |
| STS-15 | T | — | Deferred, not built |  |  |  |  |
| STS-16 | T | — | Deferred, not built |  |  |  |  |
| STS-17 | T | 7 |  |  |  |  |  |
| STS-18 | T | 2 | `test_STS_18_watchdog_kicks_are_counted` | vcan | partial: desktop `watchdog_kick()` only; hang detection in step 2 | 2026-11-13 | CI, PR step-1-interfaces |
| STS-19 | T | 2 |  |  |  |  |  |
| STS-20 | T | 8 |  |  |  |  |  |
| STS-21 | T | — | Deferred, not built |  |  |  |  |
| STS-22 | T | — | Deferred, not built |  |  |  |  |
| STS-23 | T | 7 |  |  |  |  |  |
| LAP-1 | D | 8 |  |  |  |  |  |
| LAP-2 | D | 7 |  |  |  |  |  |
| LAP-3 | D | 7 |  |  |  |  |  |
| LAP-4 | T | 7 |  |  |  |  |  |
| LAP-5 | T | 7 |  |  |  |  |  |
| LAP-6 | T | 7 |  |  |  |  |  |
| LAP-8 | T | 7 |  |  |  |  |  |
| LAP-9 | T | 7 |  |  |  |  |  |
| LAP-10 | D | 7 |  |  |  |  |  |
| LAP-11 | T | 7 |  |  |  |  |  |
| LAP-12 | D | 7 |  |  |  |  |  |
| LAP-13 | D | 7 |  |  |  |  |  |
| LAP-14 | D | 6 / 7 |  |  |  |  |  |
| LAP-15 | D | 7 |  |  |  |  |  |
| LAP-16 | T | — | Deferred, not built |  |  |  |  |
| LAP-17 | D | 7 |  |  |  |  |  |
| HW-1 | I, T | 8 |  |  |  |  |  |
| HW-2 | I | 2a / 8 |  |  |  |  |  |
| HW-3 | T | 8 |  |  |  |  |  |
| HW-4 | I | 2a |  |  |  |  |  |
| HW-5 | T | — | Deferred, not built |  |  |  |  |
| HW-6 | T | 8 |  |  |  |  |  |
| HW-7 | T | 8 |  |  |  |  |  |
| HW-8 | T | 8 | `test_HW_8_on_wake_reports_wake_and_ready_times` | vcan | partial: desktop `on_wake()` only; ready time measured in A6, step 8 | 2026-11-13 | CI, PR step-1-interfaces |
| HW-9 | I | 8 |  |  |  |  |  |
| HW-10 | I | 8 |  |  |  |  |  |
| PLT-1 | I | 2a |  |  |  |  |  |
| PLT-2 | T | 8 | `test_PLT_2_open_can_*` (vcan0), `test_PLT_2_fault_plan_*`, `test_PLT_2_fault_op_*` | vcan | partial: desktop half (kernel timestamps, own frames); controller features on hardware in B-PLT2, step 8 | 2026-11-13 | CI, PR step-1-interfaces |
| PLT-3 | I, T | 8 |  |  |  |  |  |
| PLT-4 | T | — | Deferred, not built |  |  |  |  |
| PLT-5 | I | 8 | `test_PLT_5_paths_*` | vcan | partial: desktop `paths()` keeps card, flash and keys apart; ext4 check in step 8 | 2026-11-13 | CI, PR step-1-interfaces |
| PLT-6 | I, D | 2a / 8 |  |  |  |  |  |
| PLT-7 | A | 8 |  |  |  |  |  |
| PLT-8 | I, T | 8 |  |  |  |  |  |
