# Verification matrix

One row per requirement in `docs/requirements.md`. Update the rows a build step touches at the end of that step (hand-off build plan); Beacon go/no-go results from step 2a are recorded here too.

- **Step:** the build step whose merge makes the row required by the coverage check (DC-2); for requirements verified by D, I or A only, the step in `bench/checklists.md`; — for Deferred rows.
- **Test or procedure:** the test name (it starts with the requirement ID) or the `bench/` procedure and step.
- **Where:** vcan, Beacon, backup platform, or not verified.
- **Result:** pass, fail, or not supported on the Beacon, with the reason.
- **Evidence:** the CI run, test report section or results file.

The goal is a Beacon result for every hardware-relevant T requirement. If a Beacon check fails or time runs out, the vcan build is handed over and each gap is recorded here (Where: not verified, or Result: not supported on the Beacon, with the reason) and summarized in `docs/transition.md` §2 (decisions X9, X12).

A CI check (`tools/check_verification.py`, staged by DC-2) fails if a requirement marked T has no test once its Step has merged, skipping Deferred rows. For step 8 requirements, a `bench/` procedure ID in the Test-or-procedure column satisfies the check. Before a release tag the check requires every T row to have a passing test, a procedure with a result, or a recorded gap.

**Merged build steps:** 1, 2. *(The pull request that completes a build step adds it here; `tools/check_verification.py` reads this line.)*

| ID | Method | Step | Test or procedure | Where | Result | Date | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SC-1 | I, T | 8 |  |  |  |  |  |
| SC-2 | T | 3 | `test_SC_2_read_batch_never_waits_and_keeps_order` | vcan | partial: capture reading side; bit-rate confirmation in step 3 | 2026-11-13 | CI, PR step-1-logic |
| SC-3 | T | 5 |  |  |  |  |  |
| SC-4 | T | 8 |  |  |  |  |  |
| SC-5 | D | 8 |  |  |  |  |  |
| SC-6 | I, A | 9 | `tests/contract/` (`test_SC_6_*`), import-linter layers contract | vcan | partial: platform Protocol conformance, public names and layering in CI; inspection and analysis in step 9 | 2026-11-13 | CI, PR step-1-interfaces |
| SC-8 | D | 2 | `demo/run_demo.sh` (CI step) | vcan | pass: the logger runs unchanged on desktop Linux against vcan0, replaying recorded traffic with canplayer | 2026-11-13 | CI, PR step-2-verify-demo |
| SC-9 | T | 8 |  |  |  |  |  |
| SC-10 | T | 8 |  |  |  |  |  |
| SC-11 | T | 8 |  |  |  |  |  |
| SC-12 | T | — | Deferred, not built |  |  |  |  |
| SC-12a | T | 1 | `test_SC_12a_*` (tests/malformed) | vcan | partial: decode under Hypothesis; monitor joins in step 4 | 2026-11-13 | CI, PR step-1-logic |
| NP-1 | T | 3 |  |  |  |  |  |
| NP-2 | T | 3 |  |  |  |  |  |
| NP-3 | T | 3 | `test_NP_3_*` | vcan | partial: bus-off and TX error-passive read from error frames; disable drops the queue; session wiring in PR 3 | 2026-11-13 | CI, PR step-3-transmit |
| NP-4 | T | 3 | `test_NP_4_*` | vcan | partial: address choice from 247 down skipping inventory, claimed and reserved; witness in PR 3 | 2026-11-14 | CI, PR step-3-address-requests |
| NP-5 | I, T | 3 | `test_NP_5_logger_name_is_arbitrary_address_capable_and_maximal` | vcan | pass: the configured NAME is arbitrary-address-capable, on-highway, every other field at maximum | 2026-11-14 | CI, PR step-3-address-requests |
| NP-6 | T | 3 | `test_NP_6_nothing_but_claims_for_250_ms_after_a_claim` | vcan | partial: transmit holds other traffic 250 ms after a claim; address module in PR 2 | 2026-11-13 | CI, PR step-3-transmit |
| NP-7 | T | 3 | `test_NP_7_*` | vcan | partial: concedes, one more address, then Cannot Claim from 254; witness in PR 3 | 2026-11-14 | CI, PR step-3-address-requests |
| NP-8 | T | 3 | `test_NP_8_*` | vcan | partial: answers Request for Address Claim, NACKs other requests to the logger, ignores Commanded Address; witness in PR 3 | 2026-11-14 | CI, PR step-3-address-requests |
| NP-9 | T | 3 | `test_NP_9_oversize_rts_to_logger_gets_connection_abort`, `test_NP_9_*`, `test_NP_9_never_requests_outside_the_request_allow_list` | vcan | partial: decode asks for Connection Abort; transmit in step 3; partial: transmit guard refuses and turns off on every breach type, sends only allow-listed frames, CTS/EOMA for transfers to the logger; witness on vcan0 in step 3 PR 3; requests never asks for a PGN outside the request allow-list | 2026-11-14 | CI, PR step-3-address-requests |
| NP-11 | T | 3 | `test_NP_11_*` | vcan | partial: sweep at start and every 10 minutes; session wiring in PR 3 | 2026-11-14 | CI, PR step-3-address-requests |
| NP-12 | T | 3 | `test_NP_11_session_start_sweeps_then_asks_time_date_and_vin_of_vin_sa` | vcan | partial: Time/Date and VIN to requests.vin_sa at start; vin_check in PR 3 | 2026-11-14 | CI, PR step-3-address-requests |
| NP-13 | T | 3 | `test_NP_13_known_name_is_not_asked_for_identity` | vcan | partial: identity requests only for SAs without a known NAME | 2026-11-14 | CI, PR step-3-address-requests |
| NP-14 | T | 3 | `test_NP_14_*` | vcan | pass: 1.25 s timeout, one retry, reply/NACK/no reply recorded, failed requests not repeated | 2026-11-14 | CI, PR step-3-address-requests |
| NP-15 | T | 3 | `test_NP_15_own_frames_and_replies_to_logger_are_marked`, `test_NP_15_frames_sent_through_the_handle_come_back_marked_own` | vcan | partial: decode marks own frames and replies; exclusion from detection in step 4; frames sent through capture's handle come back marked own (vcan0) | 2026-11-13 | CI, PR step-3-transmit |
| NP-16 | T | 3 | `test_NP_16_*` | vcan | partial: no more than 10 frames in any 1 s, one outstanding request per destination, protocol first; witness in PR 3 | 2026-11-13 | CI, PR step-3-transmit |
| NP-17 | T | 3 | `test_NP_17_no_bitrate_fault_gives_none_while_active`, `test_NP_17_can_missing_fault_raises_platform_error`, `test_NP_17_missing_interface_raises_can_missing`, `test_NP_17_interface_down_raises_can_down_from_read_batch`, `test_NP_17_can_down_fault_plan_reaches_read_batch`, `test_NP_17_missing_interface_raises_can_missing_on_start`, `test_NP_17_nothing_is_sent_before_transmit_is_enabled`, `test_NP_17_send_handle_without_a_socket_raises_can_down` | vcan | partial: desktop platform fault injection only; logger behaviour in step 3; capture raises can_missing and can_down; nothing sent before transmit is enabled | 2026-11-13 | CI, PR step-3-transmit |
| NP-18 | T | 3 | `test_NP_18_*` | vcan | partial: ENOBUFS and breaches turn transmit off for the session, never back on; session wiring in PR 3 | 2026-11-13 | CI, PR step-3-transmit |
| NP-19 | T | 3 |  |  |  |  |  |
| TRN-2 | D | 6 / 8 |  |  |  |  |  |
| TRN-3 | T | 6 |  |  |  |  |  |
| TRN-4 | D | 7 |  |  |  |  |  |
| TRN-5 | D | 7 |  |  |  |  |  |
| TRN-6 | I | 6 |  |  |  |  |  |
| TRN-7 | I | 6 |  |  |  |  |  |
| TRN-9 | T | 6 | `test_TRN_9_untrained_session_caps_severity_at_notice` | vcan | partial: severity cap without an inventory; untrained header and light in steps 2 and 7 | 2026-11-13 | CI, PR step-1-logic |
| TRN-10 | T | 6 |  |  |  |  |  |
| TRN-11 | T | 6 |  |  |  |  |  |
| TRN-12 | T | 6 |  |  |  |  |  |
| TRN-13 | I | 6 |  |  |  |  |  |
| TRN-14 | T | 6 |  |  |  |  |  |
| TRN-15 | T | 6 |  |  |  |  |  |
| DET-1 | T | 1 | `test_DET_1_*` | vcan | pass (step 1 minimal detect, DC-9): a NAME not in the inventory opens a connection; full detect in step 4 | 2026-11-13 | CI, PR step-1-logic |
| DET-2 | T | 4 |  |  |  |  |  |
| DET-3 | T | 4 |  |  |  |  |  |
| DET-4 | T | 4 | `test_DET_4_own_claims_are_not_contests`, `test_NP_7_concedes_tries_once_more_then_cannot_claim` | vcan | partial: the logger's own claim loss is an address_conflict record; full DET-4 in step 4 | 2026-11-14 | CI, PR step-3-address-requests |
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
| DET-15 | T | 4 | `test_DET_15_same_name_claiming_again_is_one_connection` | vcan | partial: one connection per NAME; non-claiming devices in step 4 | 2026-11-13 | CI, PR step-1-logic |
| DET-16 | T | 1 | `test_DET_16_new_claim_gives_synced_chained_connection_start`, `test_DET_16_connection_start_within_2_s_on_vcan0` | vcan | pass: connection_start written and synced within 2 s of the claim on vcan0; new-device light in step 7 | 2026-11-13 | CI, PR step-1-logic |
| DET-17 | T | 4 | `test_DET_17_approved_external_device_gets_info_short_form` | vcan | partial: info connection_start for an approved device; its end record in step 4 | 2026-11-13 | CI, PR step-1-logic |
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
| LOG-2 | T | 2 | `test_LOG_2_roll_over_continues_rec_and_chain_in_part_2`, `test_LOG_2_parts_are_checked_in_order_with_continuing_record_numbers` | vcan | pass: roll-over ends the part with session_end, the next part starts with session_start, rec and the chain continue (DC-10, DC-11); verifier checks parts in order | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-3 | I, T | 2 | `test_LOG_3_*`, `test_LOG_3_sync_thread_syncs_every_interval` | vcan | partial: one write() per record, O_APPEND, sync_now(); periodic sync thread in step 2; periodic sync thread | 2026-11-13 | CI, PR step-2-session |
| LOG-4 | I | 1 | `test_LOG_4_*` | vcan | partial: common fields, key order and time formats written by eventlog; veh_time and elapsed-mode utc in step 2 | 2026-11-13 | CI, PR step-1-logic |
| LOG-5 | T | 1 | `test_LOG_5_*`, `test_LOG_5_state_json_is_on_internal_flash_not_the_card`, `test_LOG_5_state_unwritable_hits_state_json_only`, `test_LOG_5_state_json_written_at_start_and_end`, `test_LOG_5_numbering_uses_the_higher_of_state_json_and_the_card`, `test_LOG_5_blank_card_with_state_file_is_a_new_card`, `test_LOG_5_corrupt_state_with_sessions_continues_from_the_card`, `test_LOG_5_new_card_is_a_declared_break_not_a_failure` | vcan | partial: hash rule (every session 142 hash reproduced) and chain within a file; chain across sessions and state.json in step 2; store keeps state.json on flash; numbering, new card, corrupt state, chain across sessions; verifier reports a new card as a declared break | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-6 | I | 2 | `test_LOG_6_session_start_header_has_every_field` | vcan | partial: every header field present; VIN, address and restart guard are placeholders until step 3 (DC-11) | 2026-11-13 | CI, PR step-2-session |
| LOG-7 | T | 4 |  |  |  |  |  |
| LOG-8 | I | 7 |  |  |  |  |  |
| LOG-9 | T | 3 | `test_LOG_9_first_sweep_is_logged_then_only_changes` | vcan | partial: sweep records for the first sweep and changes; written by session in PR 3 | 2026-11-14 | CI, PR step-3-address-requests |
| LOG-10 | T | 6 | `test_LOG_10_ring_keeps_raw_before_s_plus_2_seconds`, `test_LOG_10_window_includes_both_ends` | vcan | partial: capture ring and window; rawcap in step 6 | 2026-11-13 | CI, PR step-1-logic |
| LOG-11 | T | 6 |  |  |  |  |  |
| LOG-12 | T | 2 | `test_LOG_12_*` | vcan | pass: clean end and power loss (bytes cut off) recognized at the next start; the summary gap is shown by the laptop in step 7 | 2026-11-13 | CI, PR step-2-session |
| LOG-13 | I | 2 |  |  |  |  |  |
| LOG-14 | T | 2 | `test_LOG_14_*` | vcan | pass: two sessions verify as one chain; a changed, deleted or missing record or file is named; truncated last line reported as truncated; laptop last hash checked; the demo verifies the chain in CI | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-15 | T | 2 | `test_LOG_15_*`, `test_LOG_15_header_and_end_carry_buffer_size_and_kernel_drops` | vcan | partial: capture stats (buffer read back, kernel drops, frames by type) and kernel timestamps; session_start and session_end fields in step 2; session_start buffer size and session_end kernel drops | 2026-11-13 | CI, PR step-2-session |
| LOG-16 | T | 2 | `test_LOG_16_fakeclock_*`, `test_LOG_16_now_reads_the_fake_clock`, `test_LOG_16_rtc_invalid_*`, `test_LOG_16_clock_jump_*`, `test_LOG_16_host_clock_used_without_fake_clock`, `test_LOG_16_parse_time_date`, `test_LOG_16_rtc_source_*`, `test_LOG_16_elapsed_*`, `test_LOG_16_never_waits_*`, `test_LOG_16_vehicle_time_*`, `test_LOG_16_first_time_date_*`, `test_LOG_16_skew_*`, `test_LOG_16_clock_jump_does_not_move_monotonic_timers`, `test_LOG_16_own_and_other_pgns_ignored`, `test_LOG_16_veh_time_is_none_before_time_date_then_whole_seconds`, `test_LOG_16_elapsed_s_counts_from_wake`, `test_LOG_16_without_valid_time_file_is_noclock_and_records_carry_elapsed_s` | vcan | partial: FakeClock and desktop `now()`/`rtc_ok()` only; `clock` module tests come with step 1 PR 2; clock module: source choice, vehicle offset, skew fault, jumps; clock v2 veh_time and elapsed_s (DC-10); no-clock session files and elapsed_s | 2026-11-13 | CI, PR step-2-session |
| LOG-17 | T | 2 | `test_LOG_17_key_off_after_30_s_silence_then_new_session_on_next_frame` | vcan | partial: session ends after 30 s silence and the next frame opens a new session; open connections end with key-off in step 4 | 2026-11-13 | CI, PR step-2-session |
| LOG-18 | T | 2 | `test_LOG_18_restart_cause_is_read_back_by_the_next_session`, `test_LOG_18_software_restart_cause_from_the_diagnostic_log` | vcan | partial: restart cause kept for the next session; the header in PR 2; next header records software restart | 2026-11-13 | CI, PR step-2-session |
| LOG-19 | T, I | 2 | `test_LOG_19_unknown_formats_are_refused`, `test_LOG_19_unknown_format_is_refused` | vcan | partial: config, inventory and library refuse unknown formats; verifier in PR 3; verifier refuses an unknown session format (exit code 2) | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-20 | T | 2 | `test_LOG_20_*` | vcan | partial: diagnostic log format, repeat counting, rotation; session logging into it in PR 2 | 2026-11-13 | CI, PR step-2-store-config |
| LOG-21 | T | — | Deferred, not built |  |  |  |  |
| LOG-22 | T | 6 | `test_LOG_22_*`, `test_LOG_22_card_write_error_gives_high_fault_and_keeps_old_file`, `test_LOG_22_storage_fault_is_logged_after_the_card_returns` | vcan | partial: platform fault(op) and eventlog storage faults; reserve and card-full handling in step 6; store storage faults; session logs storage faults once the card returns | 2026-11-13 | CI, PR step-2-session |
| LOG-23 | T | 2 | `test_LOG_23_*` | vcan | partial: store writes atomically (temporary file, sync, rename, directory sync), never overwrites versions, ignores leftover temporary files; status file written by session in PR 2 | 2026-11-13 | CI, PR step-2-store-config |
| LOG-24 | T | — | Deferred, not built |  |  |  |  |
| STS-1 | D | 8 | `test_STS_1_set_light_*` | vcan | partial: desktop `set_light()` patterns only; light priority in step 7, A8 in step 8 | 2026-11-13 | CI, PR step-1-interfaces |
| STS-2 | D | 7 / 8 |  |  |  |  |  |
| STS-3 | I | 7 |  |  |  |  |  |
| STS-4 | I, D | 8 |  |  |  |  |  |
| STS-5 | D | 7 / 8 |  |  |  |  |  |
| STS-7 | D | 7 |  |  |  |  |  |
| STS-8 | I | 9 |  |  |  |  |  |
| STS-9 | T | 7 | `test_STS_9_*` | vcan | partial: validation, allow-list and move-grace rejection, weakening flags and records; push from the laptop in step 7 | 2026-11-13 | CI, PR step-2-store-config |
| STS-10 | T | — | Deferred, not built |  |  |  |  |
| STS-11 | T | 7 |  |  |  |  |  |
| STS-12 | T | 7 |  |  |  |  |  |
| STS-13 | T | — | Deferred, not built |  |  |  |  |
| STS-14 | T | — | Deferred, not built |  |  |  |  |
| STS-15 | T | — | Deferred, not built |  |  |  |  |
| STS-16 | T | — | Deferred, not built |  |  |  |  |
| STS-17 | T | 7 |  |  |  |  |  |
| STS-18 | T | 2 | `test_STS_18_watchdog_kicks_are_counted`, `test_STS_18_watchdog_is_kicked_on_every_loop` | vcan | partial: desktop `watchdog_kick()` only; hang detection in step 2; main loop kicks the watchdog | 2026-11-13 | CI, PR step-2-session |
| STS-19 | T | 2 | `test_STS_19_*`, `test_STS_19_corrupt_inventory_runs_untrained_with_high_fault` | vcan | partial: corrupt config and inventory detected; start-up self-check in PR 2; corrupt inventory runs untrained with a high fault | 2026-11-13 | CI, PR step-2-session |
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
