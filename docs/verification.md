# Verification matrix

One row per requirement in `docs/requirements.md`. Update the rows a build step touches at the end of that step (hand-off build plan); Beacon go/no-go results from step 2a are recorded here too.

- **Step:** the build step whose merge makes the row required by the coverage check (DC-2); for requirements verified by D, I or A only, the step in `bench/checklists.md`; — for Deferred rows.
- **Test or procedure:** the test name (it starts with the requirement ID) or the `bench/` procedure and step.
- **Where:** vcan, Beacon, backup platform, or not verified.
- **Result:** pass, fail, or not supported on the Beacon, with the reason.
- **Evidence:** the CI run, test report section or results file.

The goal is a Beacon result for every hardware-relevant T requirement. If a Beacon check fails or time runs out, the vcan build is handed over and each gap is recorded here (Where: not verified, or Result: not supported on the Beacon, with the reason) and summarized in `docs/transition.md` §2 (decisions X9, X12).

A CI check (`tools/check_verification.py`, staged by DC-2) fails if a requirement marked T has no test once its Step has merged, skipping Deferred rows. For step 8 requirements, a `bench/` procedure ID in the Test-or-procedure column satisfies the check. Before a release tag the check requires every T row to have a passing test, a procedure with a result, or a recorded gap.

**Merged build steps:** 1, 2, 3, 4, 5. *(The pull request that completes a build step adds it here; `tools/check_verification.py` reads this line.)*

| ID | Method | Step | Test or procedure | Where | Result | Date | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SC-1 | I, T | 8 |  |  |  |  |  |
| SC-2 | T | 3 | `test_SC_2_read_batch_never_waits_and_keeps_order`, `test_NP_2_channel_switches_to_normal_mode_after_the_bit_rate_is_confirmed` | vcan | pass on vcan: rate taken from the platform at 250 and 500 kbit/s; on hardware in A1 (step 8) | 2026-11-14 | CI, PR step-3-session |
| SC-3 | T | 5 | `test_SC_3_a_device_is_detected_and_identified_from_message_content` | vcan | pass on vcan: detected, monitored and identified from message content in the session; verified through the DET and IDN rows | 2026-11-14 | CI, PR step-5-session |
| SC-4 | T | 8 |  |  |  |  |  |
| SC-5 | D | 8 |  |  |  |  |  |
| SC-6 | I, A | 9 | `tests/contract/` (`test_SC_6_*`), import-linter layers contract | vcan | partial: platform Protocol conformance, public names and layering in CI; inspection and analysis in step 9 | 2026-11-13 | CI, PR step-1-interfaces |
| SC-8 | D | 2 | `demo/run_demo.sh` (CI step) | vcan | pass: the logger runs unchanged on desktop Linux against vcan0, replaying recorded traffic with canplayer | 2026-11-13 | CI, PR step-2-verify-demo |
| SC-9 | T | 8 |  |  |  |  |  |
| SC-10 | T | 8 |  |  |  |  |  |
| SC-11 | T | 8 |  |  |  |  |  |
| SC-12 | T | — | Deferred, not built |  |  |  |  |
| SC-12a | T | 1 | `test_SC_12a_*` (tests/malformed), `test_SC_12a_monitor_never_raises_and_stays_within_the_limits` | vcan | pass on vcan: decode and monitor under Hypothesis | 2026-11-14 | CI, PR step-4-monitor |
| NP-1 | T | 3 | `test_NP_1_claim_first_then_header_with_the_claim_result_then_requests`, `test_NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s` | vcan | pass on vcan: listen-only until the bit rate is confirmed; nothing sent before; A1, A2 on hardware (step 8) | 2026-11-14 | CI, PR step-3-session |
| NP-2 | T | 3 | `test_NP_2_channel_switches_to_normal_mode_after_the_bit_rate_is_confirmed` | vcan | pass on vcan: normal mode after confirmation; A2 on hardware | 2026-11-14 | CI, PR step-3-session |
| NP-3 | T | 3 | `test_NP_3_*`, `test_NP_3_bus_off_turns_transmit_off_for_the_session` | vcan | pass on vcan: bus-off turns transmit off for the session, fault logged, bus_off in session_end | 2026-11-14 | CI, PR step-3-session |
| NP-4 | T | 3 | `test_NP_4_*`, `test_NP_7_contest_at_247_concedes_and_claims_246` | vcan | pass on vcan | 2026-11-14 | CI, PR step-3-session |
| NP-5 | I, T | 3 | `test_NP_5_logger_name_is_arbitrary_address_capable_and_maximal` | vcan | pass: the configured NAME is arbitrary-address-capable, on-highway, every other field at maximum | 2026-11-14 | CI, PR step-3-address-requests |
| NP-6 | T | 3 | `test_NP_6_nothing_but_claims_for_250_ms_after_a_claim`, `test_NP_1_claim_first_then_header_with_the_claim_result_then_requests` | vcan | pass on vcan: no other traffic for 250 ms after the claim | 2026-11-14 | CI, PR step-3-session |
| NP-7 | T | 3 | `test_NP_7_*`, `test_NP_7_contest_at_247_concedes_and_claims_246` | vcan | pass on vcan: concedes and claims the next address; A3 on hardware | 2026-11-14 | CI, PR step-3-session |
| NP-8 | T | 3 | `test_NP_8_*`, `test_NP_8_request_to_the_logger_is_nacked` | vcan | pass on vcan | 2026-11-14 | CI, PR step-3-session |
| NP-9 | T | 3 | `test_NP_9_oversize_rts_to_logger_gets_connection_abort`, `test_NP_9_*`, `test_NP_9_never_requests_outside_the_request_allow_list`, `test_NP_9_rts_to_the_logger_gets_cts`, `test_NP_9_witness_on_vcan0_sees_only_allowed_frames_within_the_rate_cap` | vcan | pass on vcan: the witness sees only allow-listed frames; A3 on hardware | 2026-11-14 | CI, PR step-3-session |
| NP-11 | T | 3 | `test_NP_11_*`, `test_NP_1_claim_first_then_header_with_the_claim_result_then_requests` | vcan | pass on vcan: sweep after claiming and every 10 minutes | 2026-11-14 | CI, PR step-3-session |
| NP-12 | T | 3 | `test_NP_11_session_start_sweeps_then_asks_time_date_and_vin_of_vin_sa`, `test_NP_12_vin_reply_gives_vin_check_match` | vcan | pass on vcan: Time/Date and VIN to requests.vin_sa; vin_check record (DC-12) | 2026-11-14 | CI, PR step-3-session |
| NP-13 | T | 3 | `test_NP_13_known_name_is_not_asked_for_identity`, `test_NP_13_new_device_is_asked_for_its_identity` | vcan | pass on vcan | 2026-11-14 | CI, PR step-3-session |
| NP-14 | T | 3 | `test_NP_14_*`, `test_NP_14_no_vin_reply_gives_vin_check_unavailable` | vcan | no reply recorded in the session | 2026-11-14 | CI, PR step-3-session |
| NP-15 | T | 3 | `test_NP_15_own_frames_and_replies_to_logger_are_marked`, `test_NP_15_frames_sent_through_the_handle_come_back_marked_own`, `test_NP_15_own_frames_and_replies_to_the_logger_are_not_monitored`, `test_NP_15_ack_naming_the_logger_is_a_reply_to_it`, `test_NP_15_ack_naming_another_address_is_not`, `test_NP_15_ecu_nack_to_the_logger_is_not_a_new_pgn` | vcan | pass on vcan: own frames and replies to the logger, including Acknowledgments naming it (DC-16), are excluded from detect and monitor | 2026-11-14 | CI, PR step-4-gaps |
| NP-16 | T | 3 | `test_NP_16_*`, `test_NP_16_witness_over_a_busy_minute` | vcan | pass on vcan: witness over a busy minute with ten new devices | 2026-11-14 | CI, PR step-3-session |
| NP-17 | T | 3 | `test_NP_17_no_bitrate_fault_gives_none_while_active`, `test_NP_17_can_missing_fault_raises_platform_error`, `test_NP_17_missing_interface_raises_can_missing`, `test_NP_17_interface_down_raises_can_down_from_read_batch`, `test_NP_17_can_down_fault_plan_reaches_read_batch`, `test_NP_17_missing_interface_raises_can_missing_on_start`, `test_NP_17_nothing_is_sent_before_transmit_is_enabled`, `test_NP_17_send_handle_without_a_socket_raises_can_down`, `test_NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s` | vcan | pass on vcan: nothing sent without a bit rate; high fault after 60 s | 2026-11-14 | CI, PR step-3-session |
| NP-18 | T | 3 | `test_NP_18_*`, `test_NP_18_send_error_turns_transmit_off_with_a_high_fault` | vcan | pass on vcan: send error turns transmit off with a high fault | 2026-11-14 | CI, PR step-3-session |
| NP-19 | T | 3 | `test_NP_19_restart_loop_starts_listen_only_with_a_high_fault` | vcan | pass on vcan: three unclean starts in 10 minutes start listen-only with a high fault; cleared by a clean end; systemd limits in step 8 | 2026-11-14 | CI, PR step-3-session |
| TRN-2 | D | 6 / 8 |  |  |  |  |  |
| TRN-3 | T | 6 | `test_TRN_3_training_stops_observing_at_the_timeout` | vcan | partial: observation stops at training.timeout_min; inventory built; wired into the session in step 6 PR 3 | 2026-11-14 | CI, PR step-6-inventory |
| TRN-4 | D | 7 |  |  |  |  |  |
| TRN-5 | D | 7 |  |  |  |  |  |
| TRN-6 | I | 6 |  |  |  |  |  |
| TRN-7 | I | 6 |  |  |  |  |  |
| TRN-9 | T | 6 | `test_TRN_9_untrained_session_caps_severity_at_notice` | vcan | partial: severity cap without an inventory; untrained header and light in steps 2 and 7 | 2026-11-13 | CI, PR step-1-logic |
| TRN-10 | T | 6 | `test_TRN_10_*` | vcan | partial: PGN sent or requested and address approvals, control-PGN warning recorded, other records refused; inventory built; wired into the session in step 6 PR 3 | 2026-11-14 | CI, PR step-6-inventory |
| TRN-11 | T | 6 | `test_TRN_11_training_and_approvals_never_change_the_inventory_they_read` | vcan | partial: training and approvals only produce new versions; inventory built; wired into the session in step 6 PR 3 | 2026-11-14 | CI, PR step-6-inventory |
| TRN-12 | T | 6 | `test_TRN_12_*` | vcan | partial: conditions from EEC1, CCVS and PTO1 (or declared PTO), PGNs per ECU in each; inventory built; wired into the session in step 6 PR 3 | 2026-11-14 | CI, PR step-6-inventory |
| TRN-13 | I | 6 |  |  |  |  |  |
| TRN-14 | T | 6 | `test_TRN_14_removing_a_device_retires_its_entry`, `test_TRN_14_the_logger_is_never_part_of_the_inventory` | vcan | partial: removal record and retired IDs; the logger is never an entry; inventory built; wired into the session in step 6 PR 3 | 2026-11-14 | CI, PR step-6-inventory |
| TRN-15 | T | 6 | `test_TRN_15_removing_one_pgn_sent_or_requested` | vcan | partial: trained or approved PGN removed, sent or requested; inventory built; wired into the session in step 6 PR 3 | 2026-11-14 | CI, PR step-6-inventory |
| DET-1 | T | 1 | `test_DET_1_*` | vcan | pass (detect): a NAME not in the inventory opens a connection keyed by NAME; baseline ECUs get none | 2026-11-14 | CI, PR step-4-detect |
| DET-2 | T | 4 | `test_DET_2_*`, `test_DET_2_unclaimed_address_is_detected_when_the_first_sweep_completes`, `test_DET_2_without_a_bit_rate_the_wait_ends_after_first_sweep_wait_s` | vcan | pass on vcan: the first-sweep wait in the session, ended by the sweep or after first_sweep_wait_s without one; X42 fixtures by the test-script writers | 2026-11-14 | CI, PR step-4-session |
| DET-3 | T | 4 | `test_DET_3_*` | vcan | pass on vcan: replies to an unclaimed address open a connection; 254, 255, the logger and claimed addresses excluded | 2026-11-14 | CI, PR step-4-session |
| DET-4 | T | 4 | `test_DET_4_own_claims_are_not_contests`, `test_NP_7_concedes_tries_once_more_then_cannot_claim`, `test_DET_4_known_name_at_a_new_address_is_confirmed_after_the_grace`, `test_DET_4_move_to_another_known_ecus_address_is_notice`, `test_DET_4_old_address_still_sending_is_same_name_conflict`, `test_DET_4_frame_from_the_old_address_after_a_confirmed_move_conflicts`, `test_DET_4_old_address_claimed_by_another_name_is_not_a_conflict`, `test_DET_4_two_names_at_one_address` | vcan | pass on vcan: moves, same-NAME and two-NAME conflicts; the logger's own claim loss in address; A3 on hardware for the contest | 2026-11-14 | CI, PR step-4-session |
| DET-5 | T | 4 | `test_DET_5_names_appearing_and_disappearing_between_sweeps` | vcan | pass on vcan: the sweep record names NAMEs added and missing (DC-13); detect uses the sweep only for the first-sweep wait | 2026-11-14 | CI, PR step-4-detect |
| DET-6 | T | 4 | `test_DET_6_*`, `test_DET_6_key_off_ends_the_connection_before_session_end`, `test_DET_6_silence_end_while_the_bus_is_active` | vcan | pass on vcan: silence end while the bus is active, key-off ends every connection with the last frame as its end, before session_end | 2026-11-14 | CI, PR step-4-session |
| DET-7 | T | 4 | `test_DET_7_each_pgn_with_first_last_and_count`, `test_DET_7_summary_matches_the_example_connection_end_fields` | vcan | pass on vcan: PGN table with first, last and count in connection_end; carried PGNs only (DC-15) | 2026-11-14 | CI, PR step-4-session |
| DET-8 | T | 4 | `test_DET_8_first_requests_kept_in_order_and_the_rest_counted`, `test_DET_8_request_for_an_unnamed_pgn_has_no_name` | vcan | pass on vcan: first requests in order and the count dropped, in connection_end | 2026-11-14 | CI, PR step-4-session |
| DET-9 | T | 4 | `test_DET_9_control_pgn_requested_flags_once_with_a_running_count`, `test_DET_9_how_a_control_pgn_was_sent`, `test_DET_9_known_device_flags_only_untrained_control_pgns` | vcan | pass on vcan (monitor): control_flag at first occurrence, via and target SA (DC-13, DC-14); raw_capture null until step 6 | 2026-11-14 | CI, PR step-4-monitor |
| DET-10 | T | 4 | `test_DET_10_etp_is_recognized_and_counted_not_reassembled`, `test_DET_10_dm_activity_and_etp_with_the_memory_transfer_flag`, `test_DET_10_no_memory_flag_without_dm14_to_dm16` | vcan | pass on vcan: DM activity and ETP transfers with the memory flag, in connection_end | 2026-11-14 | CI, PR step-4-session |
| DET-11 | T | 4 | `test_DET_11_proprietary_pgns_listed` | vcan | pass on vcan: proprietary PGNs in connection_end | 2026-11-14 | CI, PR step-4-session |
| DET-12 | T | 4 | `test_DET_12_known_name_sending_an_untrained_pgn_once_per_session`, `test_DET_12_approved_device_requesting_outside_its_trained_set`, `test_DET_12_switch_off_gives_no_new_pgn_records`, `test_DET_12_address_claim_is_never_a_new_pgn`, `test_DET_12_known_ecu_sending_a_new_pgn_in_the_session` | vcan | pass on vcan: known_device_new_pgn once per session per NAME, PGN and direction; address claims excluded; ORNL check still open | 2026-11-14 | CI, PR step-4-session |
| DET-13 | T, A | 5 | `test_DET_13_wake_window_decides_not_in_baseline_or_external`, `test_DET_13_not_in_baseline_is_reclassified_by_requests_or_leaving_early` | vcan | pass on vcan: wake timing and reclassification rules in the session; the X15 rig check (A) is open | 2026-11-14 | CI, PR step-5-session |
| DET-14 | T | 6 |  |  |  |  |  |
| DET-15 | T | 4 | `test_DET_15_same_name_claiming_again_is_one_connection`, `test_DET_15_non_claiming_device_that_claims_keeps_its_connection`, `test_DET_15_returning_device_starts_a_new_connection` | vcan | pass (detect): keyed by NAME, or by SA until the device claims; a returning device starts a new connection | 2026-11-14 | CI, PR step-4-detect |
| DET-16 | T | 1 | `test_DET_16_new_claim_gives_synced_chained_connection_start`, `test_DET_16_connection_start_within_2_s_on_vcan0` | vcan | pass: connection_start written and synced within 2 s of the claim on vcan0; new-device light in step 7 | 2026-11-13 | CI, PR step-1-logic |
| DET-17 | T | 4 | `test_DET_17_approved_external_device_gets_info_short_form`, `test_DET_6_key_off_ends_every_open_connection` | vcan | pass on vcan: info start and short-form end for an approved device | 2026-11-14 | CI, PR step-4-session |
| DET-18 | T | 5 | `test_DET_18_*`, `test_DET_18_trailer_that_sends_requests_is_reclassified_high`, `test_DET_18_broadcast_only_trailer_stays_a_trailer_at_notice` | vcan | pass on vcan: trailer by NAME at notice; reclassified high on requests, control PGNs, memory access or a known address | 2026-11-14 | CI, PR step-5-session |
| DET-19 | T | 1 | `test_DET_19_*`, `test_DET_19_pgn_table_is_bounded_and_the_rest_counted`, `test_DET_19_open_etp_transfers_are_bounded`, `test_DET_19_detect_never_raises_and_keeps_connections_consistent` | vcan | partial: decode limits; pgns_per_conn and open ETP transfers bounded in monitor; raw_mb_per_session in step 6 | 2026-11-14 | CI, PR step-4-detect |
| IDN-1 | T | 1 | `test_IDN_1_*` | vcan | pass: NAME fields decoded as raw numbers (logger NAME, session 142 scan tool) | 2026-11-13 | CI, PR step-1-logic |
| IDN-2 | I | 5 |  |  |  |  |  |
| IDN-3 | T, A | 5 | `test_IDN_3_*` | vcan | pass on vcan: make and model precedence, disagreements, confidence from sources; A in step 8 | 2026-11-14 | CI, PR step-5-session |
| IDN-4 | T, A | 5 | `test_IDN_4_*`, `test_IDN_4_session_identifies_the_scan_tool_when_its_identity_requests_finish`, `test_IDN_4_connection_end_carries_the_final_identification_when_it_changes`, `test_IDN_4_no_final_identification_when_nothing_changed` | vcan | pass on vcan: library score, ties and profile match; identification when the identity requests finish, final_identification at connection end when it changed | 2026-11-14 | CI, PR step-5-session |
| IDN-5 | D | 5 / 8 | `test_IDN_5_corrupt_library_is_a_high_fault_and_identification_continues` | vcan | partial: library loaded from the card at start-up and its version in the header; a corrupt one is a high fault (DC-19); the bench-built library and install.sh in step 8 | 2026-11-14 | CI, PR step-5-session |
| IDN-6 | T | 5 | `test_IDN_6_connection_severity_by_category`, `test_IDN_6_identification_record_is_notice` | vcan | pass on vcan: connection severity by category with the untrained cap; connection_end takes the final severity | 2026-11-14 | CI, PR step-5-session |
| IDN-7 | T | — | Deferred, not built |  |  |  |  |
| LOG-1 | I | 2 |  |  |  |  |  |
| LOG-2 | T | 2 | `test_LOG_2_roll_over_continues_rec_and_chain_in_part_2`, `test_LOG_2_parts_are_checked_in_order_with_continuing_record_numbers` | vcan | pass: roll-over ends the part with session_end, the next part starts with session_start, rec and the chain continue (DC-10, DC-11); verifier checks parts in order | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-3 | I, T | 2 | `test_LOG_3_*`, `test_LOG_3_sync_thread_syncs_every_interval` | vcan | partial: one write() per record, O_APPEND, sync_now(); periodic sync thread in step 2; periodic sync thread | 2026-11-13 | CI, PR step-2-session |
| LOG-4 | I | 1 | `test_LOG_4_*` | vcan | partial: common fields, key order and time formats written by eventlog; veh_time and elapsed-mode utc in step 2 | 2026-11-13 | CI, PR step-1-logic |
| LOG-5 | T | 1 | `test_LOG_5_*`, `test_LOG_5_state_json_is_on_internal_flash_not_the_card`, `test_LOG_5_state_unwritable_hits_state_json_only`, `test_LOG_5_state_json_written_at_start_and_end`, `test_LOG_5_numbering_uses_the_higher_of_state_json_and_the_card`, `test_LOG_5_blank_card_with_state_file_is_a_new_card`, `test_LOG_5_corrupt_state_with_sessions_continues_from_the_card`, `test_LOG_5_new_card_is_a_declared_break_not_a_failure` | vcan | partial: hash rule (every session 142 hash reproduced) and chain within a file; chain across sessions and state.json in step 2; store keeps state.json on flash; numbering, new card, corrupt state, chain across sessions; verifier reports a new card as a declared break | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-6 | I | 2 | `test_LOG_6_session_start_header_has_every_field` | vcan | partial: every header field present; VIN, address and restart guard are placeholders until step 3 (DC-11) | 2026-11-13 | CI, PR step-2-session |
| LOG-7 | T | 4 | `test_LOG_7_connection_records_for_new_devices_and_none_for_baseline_ecus` | vcan | partial: connection records for new and approved devices, none for baseline ECUs, with identification results; raw captures in step 6 | 2026-11-14 | CI, PR step-5-session |
| LOG-8 | I | 7 |  |  |  |  |  |
| LOG-9 | T | 3 | `test_LOG_9_first_sweep_is_logged_then_only_changes`, `test_LOG_9_first_sweep_is_logged_then_only_changes` | vcan | pass on vcan: sweep records written by the session | 2026-11-14 | CI, PR step-3-session |
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
