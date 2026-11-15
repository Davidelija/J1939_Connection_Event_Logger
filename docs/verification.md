# Verification matrix

One row per requirement in `docs/requirements.md`. Update the rows a build step touches at the end of that step (hand-off build plan); Beacon go/no-go results from step 2a are recorded here too.

- **Step:** the build step whose merge makes the row required by the coverage check (DC-2); for requirements verified by D, I or A only, the step in `bench/checklists.md`; — for Deferred rows.
- **Test or procedure:** the test name (it starts with the requirement ID) or the `bench/` procedure and step.
- **Where:** vcan, Beacon, backup platform, or not verified.
- **Result:** pass, fail, or not supported on the Beacon, with the reason.
- **Evidence:** the CI run, test report section or results file.

The goal is a Beacon result for every hardware-relevant T requirement. If a Beacon check fails or time runs out, the vcan build is handed over and each gap is recorded here (Where: not verified, or Result: not supported on the Beacon, with the reason) and summarized in `docs/transition.md` §2 (decisions X9, X12).

A CI check (`tools/check_verification.py`, staged by DC-2) fails if a requirement marked T has no test once its Step has merged, skipping Deferred rows. For step 8 requirements, a `bench/` procedure ID in the Test-or-procedure column satisfies the check. Before a release tag the check requires every T row to have a passing test, a procedure with a result, or a recorded gap.

**Merged build steps:** 1, 2, 3, 4, 5, 6, 7. *(The pull request that completes a build step adds it here; `tools/check_verification.py` reads this line.)*

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
| SC-12a | T | 1 | `test_SC_12a_decode_never_raises_and_respects_tp_limit`, `test_SC_12a_flood_of_new_transfers_stays_within_limit`, `test_SC_12a_etp_frames_are_counted_and_passed_through_not_reassembled`, `test_SC_12a_saved_regressions_replay`, `test_SC_12a_regressions_folder_is_replayed`, `test_SC_12a_monitor_never_raises_and_stays_within_the_limits`, `test_SC_12a_*` (tests/malformed); nightly random seed: `.github/workflows/nightly.yml` | vcan | pass on vcan: decode (TP and ETP frames, bad lengths, out-of-order packets) and monitor under Hypothesis; per-frame malformed counts equal what was sent; saved regressions replayed in every CI run | 2026-11-14 | CI, PR step-4-monitor; ETP and exact counts, PR qc-fixes-3 |
| NP-1 | T | 3 | `test_NP_1_claim_first_then_header_with_the_claim_result_then_requests`, `test_NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s` | vcan | pass on vcan: listen-only until the bit rate is confirmed; nothing sent before; A1, A2 on hardware (step 8) | 2026-11-14 | CI, PR step-3-session |
| NP-2 | T | 3 | `test_NP_2_channel_switches_to_normal_mode_after_the_bit_rate_is_confirmed` | vcan | pass on vcan: normal mode after confirmation; A2 on hardware | 2026-11-14 | CI, PR step-3-session |
| NP-3 | T | 3 | `test_NP_3_*`, `test_NP_3_bus_off_turns_transmit_off_for_the_session`, `test_NP_3_error_passive_from_own_transmit_errors_turns_transmit_off` | vcan | pass on vcan: bus-off turns transmit off for the session, fault logged, bus_off in session_end | 2026-11-14 | CI, PR step-3-session |
| NP-4 | T | 3 | `test_NP_4_*`, `test_NP_7_contest_at_247_concedes_and_claims_246`, `test_NP_4_session_skips_baseline_247_and_246_and_claims_245` | vcan | pass on vcan | 2026-11-14 | CI, PR step-3-session |
| NP-5 | I, T | 3 | `test_NP_5_logger_name_is_arbitrary_address_capable_and_maximal`, `test_NP_5_logger_concedes_even_to_a_higher_name` | vcan | pass: the configured NAME is arbitrary-address-capable, on-highway, every other field at maximum; NAMEs in industry groups 2 to 5 are higher, and the logger concedes to them too | 2026-11-14 | CI, PR step-3-address-requests; concede test, PR qc-fixes-3 |
| NP-6 | T | 3 | `test_NP_6_nothing_but_claims_for_250_ms_after_a_claim`, `test_NP_1_claim_first_then_header_with_the_claim_result_then_requests` | vcan | pass on vcan: no other traffic for 250 ms after the claim | 2026-11-14 | CI, PR step-3-session |
| NP-7 | T | 3 | `test_NP_7_*`, `test_NP_7_contest_at_247_concedes_and_claims_246` | vcan | pass on vcan: concedes and claims the next address; A3 on hardware | 2026-11-14 | CI, PR step-3-session |
| NP-8 | T | 3 | `test_NP_8_*`, `test_NP_8_request_to_the_logger_is_nacked`, `test_NP_8_session_ignores_a_commanded_address_to_its_name` | vcan | pass on vcan | 2026-11-14 | CI, PR step-3-session |
| NP-9 | T | 3 | `test_NP_9_oversize_rts_to_logger_gets_connection_abort`, `test_NP_9_*`, `test_NP_9_never_requests_outside_the_request_allow_list`, `test_NP_9_rts_to_the_logger_gets_cts`, `test_NP_9_witness_on_vcan0_sees_only_allowed_frames_within_the_rate_cap` | vcan | pass on vcan: the witness sees only allow-listed frames; A3 on hardware | 2026-11-14 | CI, PR step-3-session |
| NP-11 | T | 3 | `test_NP_11_*`, `test_NP_1_claim_first_then_header_with_the_claim_result_then_requests`, `test_NP_11_session_sweeps_after_claiming_and_every_10_minutes` | vcan | pass on vcan: sweep after claiming and every 10 minutes | 2026-11-14 | CI, PR step-3-session |
| NP-12 | T | 3 | `test_NP_11_session_start_sweeps_then_asks_time_date_and_vin_of_vin_sa`, `test_NP_12_vin_reply_gives_vin_check_match`, `test_NP_12_train_start_requests_vin_again`, `test_NP_12_train_start_requests_vin_unless_it_already_replied` | vcan | pass on vcan: Time/Date and VIN to requests.vin_sa; vin_check record (DC-12) | 2026-11-14 | CI, PR step-3-session; train start, PR qc-fixes-3 (DC-26) |
| NP-13 | T | 3 | `test_NP_13_known_name_is_not_asked_for_identity`, `test_NP_13_new_device_is_asked_for_its_identity`, `test_NP_13_train_start_asks_identity_from_every_device_present`, `test_NP_13_identity_replies_before_train_start_are_reused` | vcan | pass on vcan | 2026-11-14 | CI, PR step-3-session; train start, PR qc-fixes-3 (DC-26) |
| NP-14 | T | 3 | `test_NP_14_timeout_retry_once_then_no_reply_and_never_repeated`, `test_NP_14_reply_value_is_kept_for_identify`, `test_NP_14_no_vin_reply_gives_vin_check_unavailable`, `test_NP_14_train_start_repeats_a_failed_request_once_and_never_again`, `test_NP_14_train_start_does_not_ask_again_for_an_answered_request` | vcan | pass on vcan: each request waits 1.25 s and is retried once; the reply, NACK or no reply is recorded; a failed request is not repeated in the session, except once at train start (DC-26); a VIN request with no reply gives `vin_check: unavailable` | 2026-11-14 | CI, PR step-3-session; DC-26, PR qc-fixes-3 |
| NP-15 | T | 3 | `test_NP_15_own_frames_and_replies_to_logger_are_marked`, `test_NP_15_frames_sent_through_the_handle_come_back_marked_own`, `test_NP_15_own_frames_and_replies_to_the_logger_are_not_monitored`, `test_NP_15_ack_naming_the_logger_is_a_reply_to_it`, `test_NP_15_ack_naming_another_address_is_not`, `test_NP_15_ecu_nack_to_the_logger_is_not_a_new_pgn` | vcan | pass on vcan: own frames and replies to the logger, including Acknowledgments naming it (DC-16), are excluded from detect and monitor | 2026-11-14 | CI, PR step-4-gaps |
| NP-16 | T | 3 | `test_NP_16_30_queued_requests_never_exceed_10_frames_in_any_second`, `test_NP_16_one_outstanding_request_per_destination_until_release`, `test_NP_16_global_requests_count_as_destination_255`, `test_NP_16_protocol_frames_go_ahead_of_queued_requests`, `test_NP_16_witness_over_a_busy_minute`, `test_NP_16_config_cannot_raise_the_rate_cap`, `test_NP_16_config_rejects_zero_or_negative_rate_limits`, `test_NP_16_transmit_clamps_to_the_release_cap` | vcan | pass on vcan: 10 frames in any second, one outstanding request per destination, protocol first; the cap is clamped in transmit and a config cannot raise it (QC-1) | 2026-11-14 | CI, PR qc-fixes-1 |
| NP-17 | T | 3 | `test_NP_17_no_bitrate_fault_gives_none_while_active`, `test_NP_17_can_missing_fault_raises_platform_error`, `test_NP_17_missing_interface_raises_can_missing`, `test_NP_17_interface_down_raises_can_down_from_read_batch`, `test_NP_17_can_down_fault_plan_reaches_read_batch`, `test_NP_17_missing_interface_raises_can_missing_on_start`, `test_NP_17_nothing_is_sent_before_transmit_is_enabled`, `test_NP_17_send_handle_without_a_socket_raises_can_down`, `test_NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s` | vcan | pass on vcan: nothing sent without a bit rate; high fault after 60 s | 2026-11-14 | CI, PR step-3-session |
| NP-18 | T | 3 | `test_NP_18_send_error_turns_transmit_off_with_a_high_fault`, `test_NP_18_enobufs_on_send_turns_transmit_off`, `test_NP_18_enobufs_from_the_fault_plan_turns_transmit_off`, `test_NP_18_transmit_never_turns_back_on_in_the_session`, `test_NP_18_unexpected_error_in_requests_turns_transmit_off_and_logging_continues`, `test_NP_18_error_inside_transmit_disable_still_keeps_logging`, `test_NP_18_unexpected_error_in_address_turns_transmit_off_and_logging_continues` | vcan | pass on vcan: send errors and any unexpected error in the transmit or request code turn transmit off for the session with a high fault; recording continues (QC-1) | 2026-11-14 | CI, PR qc-fixes-1 |
| NP-19 | T | 3 | `test_NP_19_restart_loop_starts_listen_only_with_a_high_fault`; (a): the systemd unit, step 8 | vcan | partial: (b) and (c) on vcan; (a) with the systemd unit in step 8 | 2026-11-14 | CI, PR step-3-session |
| TRN-2 | D | 6 / 8 | `test_TRN_2_device_that_never_claims_and_one_that_claims_late`, `test_TRN_12_training_reports_conditions_and_pgns_per_ecu_in_each`, `test_LAP_14_status_file_holds_training_coverage`; demonstration: `bench/checklists.md` TRN-2 (line 16) | vcan | partial: on vcan, training records each device's NAME, addresses and PGNs per condition (key-on engine off, idle; driving and PTO from vehicle speed and PTO1); demonstration on the rig or a truck not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| TRN-3 | T | 6 | `test_TRN_3_training_stops_observing_at_the_timeout` | vcan | pass on vcan: observation stops at training.timeout_min; the proposal waits for train finish | 2026-11-14 | CI, PR step-6-session |
| TRN-4 | D | 7 | `test_TRN_4_trained_inventory_is_saved_only_when_confirmed`, `test_TRN_4_rejected_inventory_is_not_applied` | vcan | partial: proposal shown by entry ID and applied only on y; rejection logged; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| TRN-5 | D | 7 | `test_TRN_5_approving_a_logged_device_adds_an_approved_entry`; demonstration: `bench/checklists.md` TRN-5 (line 18) | vcan | partial: on vcan, approving a logged connection adds its NAME as an approved entry without retraining; demonstration not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| TRN-6 | I | 6 | `test_TRN_6_a_saved_inventory_applies_from_the_next_session` | vcan | partial: each confirmed training, approval or removal is the next version tied to the VIN (inspection in step 8) | 2026-11-14 | CI, PR step-7-status |
| TRN-7 | I | 6 | `test_TRN_7_proposed_entries_hold_the_inventory_fields`, `test_TRN_7_example_inventory_validates`; inspection: `bench/checklists.md` TRN-7 (line 20) | vcan | partial: the tests show proposed and example entries hold the TRN-7 fields; inspection not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| TRN-9 | T | 6 | `test_TRN_9_untrained_session_caps_severity_at_notice`, `test_TRN_9_training_runs_detection_as_untrained` | vcan | pass on vcan: severity capped at notice without an inventory, during training and after a VIN mismatch; untrained header flag; needs-training light in step 7 | 2026-11-14 | CI, PR step-6-session |
| TRN-10 | T | 6 | `test_TRN_10_*` | vcan | pass on vcan: PGN and address approvals from logged events save the next version; the laptop prompt and warning line in step 7 | 2026-11-14 | CI, PR step-6-session |
| TRN-11 | T | 6 | `test_TRN_11_training_and_approvals_never_change_the_inventory_they_read`, `test_TRN_11_nothing_is_added_without_an_operator_call` | vcan | pass on vcan: nothing is added without a confirmed training or an approval | 2026-11-14 | CI, PR step-6-session |
| TRN-12 | T | 6 | `test_TRN_12_*` | vcan | pass on vcan: conditions from EEC1, CCVS and PTO1, or declared PTO, with the PGNs per ECU in each, in training_finish | 2026-11-14 | CI, PR step-6-session |
| TRN-13 | I | 6 | `test_TRN_13_example_inventory_approval_kinds_use_the_enumeration`; inspection: `bench/checklists.md` TRN-13 (line 21) | vcan | partial: the example inventory keeps trained PGNs apart from later approvals, each with reason and date, and records the vehicle configuration; inspection not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| TRN-14 | T | 6 | `test_TRN_14_removing_a_device_retires_its_entry`, `test_TRN_14_the_logger_is_never_part_of_the_inventory`, `test_TRN_14_removing_an_entry_saves_the_next_version` | vcan | pass on vcan: removal saves the next version, applied from the next session; retired IDs; the laptop warning line in step 7 | 2026-11-14 | CI, PR step-6-session |
| TRN-15 | T | 6 | `test_TRN_15_removing_one_pgn_sent_or_requested` | vcan | pass on vcan: one PGN removed, sent or requested, as the next version | 2026-11-14 | CI, PR step-6-session |
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
| DET-14 | T | 6 | `test_DET_14_vin_mismatch_is_high_and_the_session_runs_untrained` | vcan | pass on vcan: high vin_mismatch, the rest of the session untrained; no VIN reply gives unavailable (NP-14); the fault light in step 7 | 2026-11-14 | CI, PR step-6-session |
| DET-15 | T | 4 | `test_DET_15_same_name_claiming_again_is_one_connection`, `test_DET_15_non_claiming_device_that_claims_keeps_its_connection`, `test_DET_15_returning_device_starts_a_new_connection` | vcan | pass (detect): keyed by NAME, or by SA until the device claims; a returning device starts a new connection | 2026-11-14 | CI, PR step-4-detect |
| DET-16 | T | 1 | `test_DET_16_new_claim_gives_synced_chained_connection_start`, `test_DET_16_connection_start_within_2_s_on_vcan0` | vcan | pass: connection_start written and synced within 2 s of the claim on vcan0; new-device light in step 7 | 2026-11-13 | CI, PR step-1-logic |
| DET-17 | T | 4 | `test_DET_17_approved_external_device_gets_info_short_form`, `test_DET_6_key_off_ends_every_open_connection` | vcan | pass on vcan: info start and short-form end for an approved device | 2026-11-14 | CI, PR step-4-session |
| DET-18 | T | 5 | `test_DET_18_*`, `test_DET_18_trailer_that_sends_requests_is_reclassified_high`, `test_DET_18_broadcast_only_trailer_stays_a_trailer_at_notice` | vcan | pass on vcan: trailer by NAME at notice; reclassified high on requests, control PGNs, memory access or a known address | 2026-11-14 | CI, PR step-5-session |
| DET-19 | T | 1 | `test_DET_19_*`, `test_DET_19_pgn_table_is_bounded_and_the_rest_counted`, `test_DET_19_open_etp_transfers_are_bounded`, `test_DET_19_detect_never_raises_and_keeps_connections_consistent` | vcan | partial: decode limits; pgns_per_conn and open ETP transfers bounded in monitor; raw_mb_per_session in step 6 | 2026-11-14 | CI, PR step-4-detect |
| IDN-1 | T | 1 | `test_IDN_1_*` | vcan | pass: NAME fields decoded as raw numbers (logger NAME, session 142 scan tool) | 2026-11-13 | CI, PR step-1-logic |
| IDN-2 | I | 5 | `test_IDN_2_manufacturer_codes_are_read_from_the_library`; inspection: `bench/checklists.md` IDN-2 (line 23) | vcan | partial: make is decoded from the library's manufacturer list; the example library (`docs/examples/lib-v1.json`) ships the list empty with its format documented; the release library under `data/` does not exist yet (step 8); inspection not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| IDN-3 | T, A | 5 | `test_IDN_3_*` | vcan | pass on vcan: make and model precedence, disagreements, confidence from sources; A in step 8 | 2026-11-14 | CI, PR step-5-session |
| IDN-4 | T, A | 5 | `test_IDN_4_*`, `test_IDN_4_session_identifies_the_scan_tool_when_its_identity_requests_finish`, `test_IDN_4_connection_end_carries_the_final_identification_when_it_changes`, `test_IDN_4_no_final_identification_when_nothing_changed`, `test_IDN_4_score_known_answers`, `test_IDN_4_session_142_scores_at_identification_time`, `test_IDN_4_identify_sees_requests_up_to_identification_then_the_whole_connection` | vcan | pass on vcan: library score, ties and profile match; identification when the identity requests finish, final_identification at connection end when it changed | 2026-11-14 | CI, PR step-5-session |
| IDN-5 | D | 5 / 8 | `test_IDN_5_corrupt_library_is_a_high_fault_and_identification_continues` | vcan | partial: library loaded from the card at start-up and its version in the header; a corrupt one is a high fault (DC-19); the bench-built library and install.sh in step 8 | 2026-11-14 | CI, PR step-5-session |
| IDN-6 | T | 5 | `test_IDN_6_connection_severity_by_category`, `test_IDN_6_identification_record_is_notice` | vcan | pass on vcan: connection severity by category with the untrained cap; connection_end takes the final severity | 2026-11-14 | CI, PR step-5-session |
| IDN-7 | T | — | Deferred, not built |  |  |  |  |
| LOG-1 | I | 2 | `demo/run_demo.sh` (Auto), `test_LOG_17_key_off_after_30_s_silence_then_new_session_on_next_frame`; inspection: `bench/checklists.md` LOG-1 (line 27) | vcan | partial: on vcan, one JSON-lines file per session from wake to key-off; inspection on the rig not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| LOG-2 | T | 2 | `test_LOG_2_roll_over_continues_rec_and_chain_in_part_2`, `test_LOG_2_parts_are_checked_in_order_with_continuing_record_numbers` | vcan | pass: roll-over ends the part with session_end, the next part starts with session_start, rec and the chain continue (DC-10, DC-11); verifier checks parts in order | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-3 | I, T | 2 | `test_LOG_3_*`, `test_LOG_3_sync_thread_syncs_every_interval` | vcan | partial: one write() per record, O_APPEND, sync_now(); periodic sync thread in step 2; periodic sync thread | 2026-11-13 | CI, PR step-2-session |
| LOG-4 | I | 1 | `test_LOG_4_*` | vcan | partial: common fields, key order and time formats written by eventlog; veh_time and elapsed-mode utc in step 2 | 2026-11-13 | CI, PR step-1-logic |
| LOG-5 | T | 1 | `test_LOG_5_*`, `test_LOG_5_state_json_is_on_internal_flash_not_the_card`, `test_LOG_5_state_unwritable_hits_state_json_only`, `test_LOG_5_state_json_written_at_start_and_end`, `test_LOG_5_numbering_uses_the_higher_of_state_json_and_the_card`, `test_LOG_5_blank_card_with_state_file_is_a_new_card`, `test_LOG_5_corrupt_state_with_sessions_continues_from_the_card`, `test_LOG_5_new_card_is_a_declared_break_not_a_failure`, `test_LOG_5_incomplete_last_line_is_never_rewritten` | vcan | partial: hash rule (every session 142 hash reproduced) and chain within a file; chain across sessions and state.json in step 2; store keeps state.json on flash; numbering, new card, corrupt state, chain across sessions; verifier reports a new card as a declared break | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-6 | I | 2 | `test_LOG_6_session_start_header_has_every_field` | vcan | partial: every header field present; VIN, address and restart guard are placeholders until step 3 (DC-11) | 2026-11-13 | CI, PR step-2-session |
| LOG-7 | T | 4 | `test_LOG_7_connection_records_for_new_devices_and_none_for_baseline_ecus` | vcan | partial: connection records for new and approved devices, none for baseline ECUs, with identification results; raw captures in step 6 | 2026-11-14 | CI, PR step-5-session |
| LOG-8 | I | 7 | `test_LOG_8_login_and_logout_are_logged_with_the_operator` | vcan | partial: operator records written with operator and time; inspection in step 9 | 2026-11-14 | CI, PR step-7-status |
| LOG-9 | T | 3 | `test_LOG_9_first_sweep_is_logged_then_only_changes`, `test_LOG_9_first_sweep_is_logged_then_only_changes` | vcan | pass on vcan: sweep records written by the session | 2026-11-14 | CI, PR step-3-session |
| LOG-10 | T | 6 | `test_LOG_10_ring_keeps_raw_before_s_plus_2_seconds`, `test_LOG_10_window_includes_both_ends`, `test_LOG_10_window_runs_from_10_s_before_to_60_s_after_the_event`, `test_LOG_10_names_count_each_connections_captures`, `test_LOG_10_candump_format_for_extended_standard_remote_and_error_frames`, `test_LOG_10_open_captures_are_written_at_session_end`, `test_LOG_10_no_capture_once_the_session_budget_is_used`, `test_LOG_10_connection_start_names_its_raw_capture_and_the_file_is_written` | vcan | pass on vcan: raw captures from 10 s before to 60 s after each connection start and control flag, named in the record; every window contains its record's utc | 2026-11-14 | CI, PR step-6-session |
| LOG-11 | T | 6 | `test_LOG_11_*` | vcan | partial: retention frees retrieved raw captures first, then unretrieved, oldest first, raw captures only, at session start and after each capture; the retrieved list and retrieval in step 7 | 2026-11-14 | CI, PR step-6-session |
| LOG-12 | T | 2 | `test_LOG_12_*` | vcan | pass: clean end and power loss (bytes cut off) recognized at the next start; the summary gap is shown by the laptop in step 7 | 2026-11-13 | CI, PR step-2-session |
| LOG-13 | I | 2 | `test_LOG_13_example_config_validates_with_its_version`, `test_LOG_6_session_start_header_has_every_field`; inspection: `bench/checklists.md` LOG-13 (line 32) | vcan | partial: one versioned config file; its version is in each session header; inspection on the rig not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| LOG-14 | T | 2 | `test_LOG_14_*` | vcan | pass: two sessions verify as one chain; a changed, deleted or missing record or file is named; truncated last line reported as truncated; laptop last hash checked; the demo verifies the chain in CI | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-15 | T | 2 | `test_LOG_15_*`, `test_LOG_15_header_and_end_carry_buffer_size_and_kernel_drops` | vcan | partial: capture stats (buffer read back, kernel drops, frames by type) and kernel timestamps; session_start and session_end fields in step 2; session_start buffer size and session_end kernel drops | 2026-11-13 | CI, PR step-2-session |
| LOG-16 | T | 2 | `test_LOG_16_fakeclock_*`, `test_LOG_16_now_reads_the_fake_clock`, `test_LOG_16_rtc_invalid_*`, `test_LOG_16_clock_jump_*`, `test_LOG_16_host_clock_used_without_fake_clock`, `test_LOG_16_parse_time_date`, `test_LOG_16_rtc_source_*`, `test_LOG_16_elapsed_*`, `test_LOG_16_never_waits_*`, `test_LOG_16_vehicle_time_*`, `test_LOG_16_first_time_date_*`, `test_LOG_16_skew_*`, `test_LOG_16_clock_jump_does_not_move_monotonic_timers`, `test_LOG_16_own_and_other_pgns_ignored`, `test_LOG_16_veh_time_is_none_before_time_date_then_whole_seconds`, `test_LOG_16_elapsed_s_counts_from_wake`, `test_LOG_16_without_valid_time_file_is_noclock_and_records_carry_elapsed_s` | vcan | partial: FakeClock and desktop `now()`/`rtc_ok()` only; `clock` module tests come with step 1 PR 2; clock module: source choice, vehicle offset, skew fault, jumps; clock v2 veh_time and elapsed_s (DC-10); no-clock session files and elapsed_s | 2026-11-13 | CI, PR step-2-session |
| LOG-17 | T | 2 | `test_LOG_17_key_off_after_30_s_silence_then_new_session_on_next_frame` | vcan | partial: session ends after 30 s silence and the next frame opens a new session; open connections end with key-off in step 4 | 2026-11-13 | CI, PR step-2-session |
| LOG-18 | T | 2 | `test_LOG_18_restart_cause_is_read_back_by_the_next_session`, `test_LOG_18_software_restart_cause_from_the_diagnostic_log` | vcan | pass on vcan: restart cause read back; an operator restart leaves no session_end, so the next header says software restart | 2026-11-14 | CI, PR step-7-status |
| LOG-19 | T, I | 2 | `test_LOG_19_unknown_formats_are_refused`, `test_LOG_19_unknown_format_is_refused` | vcan | partial: config, inventory and library refuse unknown formats; verifier in PR 3; verifier refuses an unknown session format (exit code 2) | 2026-11-13 | CI, PR step-2-verify-demo |
| LOG-20 | T | 2 | `test_LOG_20_*` | vcan | partial: diagnostic log format, repeat counting, rotation; session logging into it in PR 2 | 2026-11-13 | CI, PR step-2-store-config |
| LOG-21 | T | — | Deferred, not built |  |  |  |  |
| LOG-22 | T | 6 | `test_LOG_22_*`, `test_LOG_22_card_write_error_gives_high_fault_and_keeps_old_file`, `test_LOG_22_storage_fault_is_logged_after_the_card_returns`, `test_LOG_22_no_capture_once_only_the_reserve_is_left`, `test_LOG_22_write_error_is_a_high_fault_not_an_exception`, `test_LOG_22_notice_at_warn_pct_once_per_session`, `test_LOG_22_only_the_reserve_left_stops_raw_captures_with_a_high_fault`, `test_LOG_22_retention_stops_raw_captures_when_only_the_reserve_is_left`, `test_LOG_22_repeated_storage_error_is_one_fault_with_a_count`, `test_LOG_22_a_single_storage_error_says_record_not_written` | vcan | pass on vcan: notice at warn_pct, high fault and raw captures stopped when only the reserve is left, storage faults from eventlog, store and rawcap; the fault light in step 7 | 2026-11-14 | CI, PR step-6-session |
| LOG-23 | T | 2 | `test_LOG_23_*`, `test_LOG_23_write_atomic_syncs_the_file_and_the_directory` | vcan | partial: store writes atomically (temporary file, sync, rename, directory sync), never overwrites versions, ignores leftover temporary files; status file written by session in PR 2 | 2026-11-13 | CI, PR step-2-store-config |
| LOG-24 | T | — | Deferred, not built |  |  |  |  |
| STS-1 | D | 8 | `test_STS_1_set_light_*`, `test_STS_1_light_priority_fast_over_slow_over_steady`, `test_STS_1_status_sets_the_light_on_change_and_writes_on_state_change` | vcan | partial: light priority and changes on the desktop platform; A8 on hardware (step 8) | 2026-11-14 | CI, PR step-7-status |
| STS-2 | D | 7 / 8 | `test_STS_2_high_events_stay_unreviewed_until_cleared` | vcan | partial: unreviewed high events kept in state.json and the light slow until cleared; the socket and j1939cmd in step 7 PR 2, the laptop in PR 3 | 2026-11-14 | CI, PR step-7-status |
| STS-3 | I | 7 | `test_STS_3_status_file_has_the_example_fields`, `test_STS_3_the_status_file_is_kept_on_the_card` | vcan | partial: status-1 file on the card with the example fields plus transmit and vin_status; inspection in step 9 | 2026-11-14 | CI, PR step-7-status |
| STS-4 | I, D | 8 |  |  |  |  |  |
| STS-5 | D | 7 / 8 | `test_STS_5_fingerprint_matches_ssh_keygen`, `test_STS_5_operator_names_come_from_the_fingerprint_file`, `test_STS_5_an_unknown_key_cannot_change_the_logger`, `test_STS_5_j1939cmd_reads_the_key_from_ssh_user_auth` | vcan | partial: operator from the SSH key fingerprint (matches ssh-keygen); unknown keys cannot change the logger; sshd, keys.sh and the wired port in step 8 (D) | 2026-11-14 | CI, PR step-7-cmdserver |
| STS-7 | D | 7 | `test_STS_7_report_has_five_sections_in_order_and_events_csv` | vcan | partial: five sections in order, events grouped by device, events.csv; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| STS-8 | I | 9 |  |  |  |  |  |
| STS-9 | T | 7 | `test_STS_9_*`, `test_STS_9_config_push_saves_a_new_version_and_logs_the_change`, `test_STS_9_weakening_needs_confirm_and_is_high`, `test_STS_9_a_bad_config_is_rejected_and_logged` | vcan | pass on vcan: config push validated, saved as the next version, weakening needs --confirm and is high, rejections logged; applies from the next session | 2026-11-14 | CI, PR step-7-j1939ctl |
| STS-10 | T | — | Deferred, not built |  |  |  |  |
| STS-11 | T | 7 | `test_STS_11_restart_logs_reset_and_ends_with_exit_code_75` | vcan | pass on vcan: reset record, exit code 75, the next session records a software restart; systemd restart in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| STS-12 | T | 7 | `test_STS_12_retrain_runs_the_next_session_untrained` | vcan | pass on vcan: inventory archived, untrained from the next session until a training is applied | 2026-11-14 | CI, PR step-7-j1939ctl |
| STS-13 | T | — | Deferred, not built |  |  |  |  |
| STS-14 | T | — | Deferred, not built |  |  |  |  |
| STS-15 | T | — | Deferred, not built |  |  |  |  |
| STS-16 | T | — | Deferred, not built |  |  |  |  |
| STS-17 | T | 7 | `test_STS_17_config_push_is_validated_on_the_laptop_first` | vcan | pass on vcan: the laptop validates before sending; weakening needs --confirm (migration deferred) | 2026-11-14 | CI, PR step-7-j1939ctl |
| STS-18 | T | 2 | `test_STS_18_watchdog_kicks_are_counted`, `test_STS_18_watchdog_is_kicked_on_every_loop` | vcan | partial: desktop `watchdog_kick()` only; hang detection in step 2; main loop kicks the watchdog | 2026-11-13 | CI, PR step-2-session |
| STS-19 | T | 2 | `test_STS_19_corrupt_config_file_is_detected`, `test_STS_19_main_without_any_config_stops_with_exit_code_2`, `test_STS_19_corrupt_inventory_is_rejected_with_reasons`, `test_STS_19_corrupt_inventory_runs_untrained_with_high_fault`, `test_STS_19_read_only_card_at_start_up_is_a_high_fault`, `test_STS_19_writable_card_at_start_up_gives_no_fault`; clock state at start-up: `test_LOG_16_never_waits_for_the_clock_with_rtc_invalid`, `test_LOG_16_elapsed_source_without_rtc_or_vehicle_time` | vcan | pass on vcan: a read-only card at start-up gives a high fault and the fault state (fast blink) before the session opens, and the fault is written once the card is writable; a corrupt config stops the logger (exit 2); a corrupt inventory runs it untrained with a high fault; the clock state (source and validity) is known from the start without waiting | 2026-11-14 | CI, PR step-2-session; card check, PR qc-fixes-3 |
| STS-20 | T | 8 |  |  |  |  |  |
| STS-21 | T | — | Deferred, not built |  |  |  |  |
| STS-22 | T | — | Deferred, not built |  |  |  |  |
| STS-23 | T | 7 | `test_STS_23_replies_follow_the_protocol_and_refuse_with_a_next_step`, `test_STS_23_*` | vcan | pass on vcan: one command at a time through the socket and main loop; service-down status and retrieve; refusals with the next step | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-1 | D | 8 |  |  |  |  |  |
| LAP-2 | D | 7 | `test_LAP_15_refusals_say_why_and_what_to_do_with_a_nonzero_exit` | vcan | partial: the 16 commands with --help; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-3 | D | 7 | `test_LAP_3_changing_commands_show_the_change_ask_a_reason_then_y_n`, `test_LAP_3_removing_a_training_ecu_shows_a_warning_line` | vcan | partial: one prompt pattern, reason, y/N, warning lines, IDs never list positions; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-4 | T | 7 | `test_LAP_4_clear_needs_unreviewed_ids_and_a_reason` | vcan | pass on vcan: clear on unreviewed IDs with one reason, review_clear logged | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-5 | T | 7 | `test_LAP_5_retrieved_files_are_logged_and_listed`, `test_LAP_5_retrieve_copies_new_files_checks_the_chain_and_tells_the_logger`, `test_LAP_5_a_same_name_file_with_other_content_is_kept_with_a_suffix` | vcan | pass on vcan: VIN folder, new files only, chain checked against the kept last hash, read-only, suffix for changed content, diagnostic log copied, retrieval logged | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-6 | T | 7 | `test_LAP_6_a_partial_copy_is_copied_again` | vcan | pass on vcan: files already held are skipped, partial copies copied again | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-8 | T | 7 | `test_LAP_8_each_header_lists_the_installed_operator_key_fingerprints` | vcan | partial: session_start lists the installed key fingerprints; release/keys.sh in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-9 | T | 7 | `test_LAP_9_the_open_session_is_copied_as_complete_records` | vcan | pass on vcan: the open session copied as complete records and reported as in progress | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-10 | D | 7 | `test_LAP_10_status_is_the_home_screen_with_a_next_step` | vcan | partial: one block with a Next step line, clock difference shown, never set; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-11 | T | 7 | `test_LAP_11_approve_clears_its_event_in_the_same_step` | vcan | pass on vcan: approve needs a reason and clears its event in the same step | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-12 | D | 7 | `test_STS_7_report_has_five_sections_in_order_and_events_csv`, `test_LAP_13_inventory_export_writes_csv_offline` | vcan | partial: report and inventory show and export on a retrieved folder; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-13 | D | 7 | `test_LAP_13_inventory_export_writes_csv_offline` | vcan | partial: inventory export writes CSV; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-14 | D | 6 / 7 | `test_LAP_14_train_status_shows_time_conditions_devices_and_pgn_counts`, `test_LAP_14_status_file_holds_training_coverage`; demonstration: `bench/checklists.md` LAP-14 (line 47) | vcan | partial: on vcan, `train status` shows elapsed and remaining time, the conditions covered and still to cover, the devices found and PGN counts per ECU, and the status file holds the same coverage; demonstration on the Windows laptop not yet signed | 2026-11-14 | CI, PR qc-fixes-3 |
| LAP-15 | D | 7 | `test_STS_23_bad_requests_are_refused_with_the_next_step` | vcan | partial: every refusal says why and what to do, non-zero exit codes, --help; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
| LAP-16 | T | — | Deferred, not built |  |  |  |  |
| LAP-17 | D | 7 | `test_LAP_17_events_use_plain_words` | vcan | partial: plain words for categories in events, train finish, inventory and report; demonstrated in tests against an in-process logger; the Windows laptop procedure (LAP-1) in step 8 | 2026-11-14 | CI, PR step-7-j1939ctl |
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

**Test levels (DC-24):** the session tests in `tests/unit/test_session_*.py` count as level 2 (component) evidence until `tests/component/` exists; no row claims level 3 (replay) beyond the two `vcan0` tests. Coverage of each communications case is in `docs/test-plan.md` §5.

## Per-clause tests for safety-critical requirements

The safety-critical rows (transmit and its limits: NP-1, NP-3, NP-9, NP-16 to NP-19; hashing: LOG-5 and LOG-14) are split here into their clauses, each with the tests that assert it, so a reviewer can check every clause without reading every test. Test names leave out the `test_` prefix; all are in `tests/unit/` unless noted. Clauses that need hardware say so. Keep this section current with the matrix above.

### NP-1: listen-only first, bit rate confirmed before transmitting
| Clause | Tests |
| --- | --- |
| Starts listen-only; nothing is sent before the bit rate is confirmed | `NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s`, `NP_17_nothing_is_sent_before_transmit_is_enabled` |
| Confirms 250 or 500 kbit/s from clean frames, then claims first | `NP_1_claim_first_then_header_with_the_claim_result_then_requests`, `SC_2_read_batch_never_waits_and_keeps_order` |
| Listen-only mode on the real controller | Hardware: A1 (step 8) |

### NP-3: bus-off or own error-passive turns transmit off for the session
| Clause | Tests |
| --- | --- |
| Bus-off and transmit error-passive are recognised; receive-only error-passive is not the logger's | `NP_3_bus_state_reads_bus_off_and_tx_error_passive` |
| Bus-off: stop transmitting, log a fault, `bus_off` in the session end | `NP_3_bus_off_turns_transmit_off_for_the_session`, `NP_3_bus_off_disable_drops_the_queue` |
| Own error-passive: stop transmitting, log a fault; receive-only error-passive keeps transmit on | `NP_3_error_passive_from_own_transmit_errors_turns_transmit_off` |
| Stays listen-only for the rest of the session | `NP_18_transmit_never_turns_back_on_in_the_session` |

### NP-9: only allowed frames, no data, no writes
| Clause | Tests |
| --- | --- |
| Only PGNs on `transmit.allow_list`, with the right identifiers | `NP_9_allowed_frames_are_sent_with_the_right_identifiers`, `NP_9_breach_is_never_sent_and_turns_transmit_off` (12 cases) |
| Config can narrow the allow-lists but never widen them | `NP_9_configured_allow_list_can_narrow_but_never_widen` |
| Requests only for `requests.allow_list` PGNs | `NP_9_never_requests_outside_the_request_allow_list` |
| Transport-protocol handshake only for transfers addressed to it (CTS, EOMA, Connection Abort) | `NP_9_rts_to_the_logger_gets_cts_then_eoma`, `NP_9_logger_asks_for_each_window_when_rts_limits_packets_per_cts`, `NP_9_oversize_rts_to_logger_gets_connection_abort`, `NP_9_transfers_between_other_nodes_get_no_replies`, `NP_9_rts_to_the_logger_gets_cts` |
| Only Cannot Claim uses the null address | `NP_9_only_cannot_claim_may_use_the_null_address` |
| Only `transmit` sends; only `session` hands it the send handle (rule 4) | `tests/contract/test_imports.py::NP_9_only_transmit_sends_and_only_session_hands_it_the_send_handle` |
| A witness on the bus sees only allowed frames | `NP_9_witness_on_vcan0_sees_only_allowed_frames_within_the_rate_cap` (vcan, CI); on hardware, the witness Beacon (step 8) |

### NP-16: at most 10 frames/s, one outstanding request per destination, protocol frames first
| Clause | Tests |
| --- | --- |
| At most 10 frames in any second | `NP_16_30_queued_requests_never_exceed_10_frames_in_any_second`, `NP_16_witness_over_a_busy_minute` |
| One outstanding request per destination; global requests count as destination 255 | `NP_16_one_outstanding_request_per_destination_until_release`, `NP_16_global_requests_count_as_destination_255` |
| Address-claim replies and NACKs go ahead of queued requests | `NP_16_protocol_frames_go_ahead_of_queued_requests` |
| Config can lower the limits but never raise them; zero or negative is refused | `NP_16_config_cannot_raise_the_rate_cap`, `NP_16_config_rejects_zero_or_negative_rate_limits`, `NP_16_transmit_clamps_to_the_release_cap` |

### NP-17: no bit rate, stay listen-only and keep trying
| Clause | Tests |
| --- | --- |
| Never transmits before a bit rate is confirmed | `NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s`, `NP_17_nothing_is_sent_before_transmit_is_enabled` |
| Keeps trying; a fault after 60 s | `NP_17_nothing_is_sent_without_a_confirmed_bit_rate_and_fault_after_60_s`, `NP_17_no_bitrate_fault_gives_none_while_active` |
| Shows the fault state | A high fault sets the light: `STS_1_light_priority_fast_over_slow_over_steady`, `STS_1_status_sets_the_light_on_change_and_writes_on_state_change` |
| Interface missing or down: retried with backoff, logged once, session kept | `NP_17_missing_interface_is_retried_with_backoff_and_logged_once`, `NP_17_interface_down_while_running_keeps_the_session_and_retries`, `NP_17_missing_interface_raises_can_missing_on_start`, `NP_17_interface_down_raises_can_down_from_read_batch`, `NP_17_can_down_fault_plan_reaches_read_batch`, `NP_17_send_handle_without_a_socket_raises_can_down`, `NP_17_missing_interface_raises_can_missing`, `NP_17_can_missing_fault_raises_platform_error` |

### NP-18: any unexpected error or breach turns transmit off for the session
| Clause | Tests |
| --- | --- |
| A frame that would break the allow-list or rate cap is never sent; transmit off; high fault | `NP_9_breach_is_never_sent_and_turns_transmit_off` (12 cases) |
| A send error (ENOBUFS) turns transmit off with a high fault | `NP_18_send_error_turns_transmit_off_with_a_high_fault`, `NP_18_enobufs_on_send_turns_transmit_off`, `NP_18_enobufs_from_the_fault_plan_turns_transmit_off` |
| An unexpected error in the request or address code turns transmit off; logging continues | `NP_18_unexpected_error_in_requests_turns_transmit_off_and_logging_continues`, `NP_18_unexpected_error_in_address_turns_transmit_off_and_logging_continues` |
| An error while turning transmit off still leaves it off, with the fault, and logging continues | `NP_18_error_inside_transmit_disable_still_keeps_logging` |
| Never turns back on in the session | `NP_18_transmit_never_turns_back_on_in_the_session` |

### NP-19: a restart loop starts listen-only
| Clause | Tests |
| --- | --- |
| (a) The service unit waits between restarts and caps them | Not yet verified: the systemd unit, step 8 (the NP-19 row is partial) |
| (b) After 3 unclean restarts in 10 minutes, the next session is listen-only: no claim, sweep or requests | `NP_19_restart_loop_starts_listen_only_with_a_high_fault` |
| (c) High fault "restart loop; transmit disabled"; detection continues | `NP_19_restart_loop_starts_listen_only_with_a_high_fault`; light: `STS_1_light_priority_fast_over_slow_over_steady` |

### LOG-5: SHA-256 hash chain
| Clause | Tests |
| --- | --- |
| The hash rule (prev as hex, then compact JSON in written order) | `LOG_5_hash_rule_reproduces_every_session_142_hash`, `LOG_5_example_session_142_hash_chain_verifies`, `LOG_14_verifier_hash_matches_the_logger` |
| Chained within a session | `LOG_5_appended_records_form_a_chain_from_prev` |
| Across sessions and parts: the first record carries the last hash before it | `LOG_14_two_sessions_verify_as_one_chain`, `LOG_2_roll_over_continues_rec_and_chain_in_part_2`, `LOG_5_example_retrieval_last_hash_is_the_chain_before_it` |
| After a power loss: the hash of the last complete record; the incomplete last line is never rewritten | `LOG_12_power_loss_reports_bytes_cut_off_and_chain_continues`, `LOG_5_incomplete_last_line_is_never_rewritten`, `LOG_5_crash_before_the_header_continues_the_chain_from_the_older_file` |
| New logger: prev of 64 zeros | `LOG_5_SN_d2_corrupt_state_with_a_blank_card_starts_session_1` |
| New card: 64 zeros, `new_card`, a declared break | `LOG_5_blank_card_with_state_file_is_a_new_card`, `LOG_5_new_card_is_a_declared_break_not_a_failure` |
| `state.json` on internal flash, written at session start and after each part | `LOG_5_state_json_is_on_internal_flash_not_the_card`, `LOG_5_state_json_written_at_start_and_end`, `LOG_5_state_unwritable_hits_state_json_only`, `LOG_5_state_unwritable_fault_hits_flash_only` |
| Next session number is one more than the higher of state and card | `LOG_5_numbering_uses_the_higher_of_state_json_and_the_card` |
| Missing or corrupt state with sessions on the card: numbering and chain continue | `LOG_5_SN_b_state_missing_with_sessions_continues_numbering_and_chain`, `LOG_5_corrupt_state_with_sessions_continues_from_the_card` |
| Flash not writable: `install.sh` asks for the next session number | Hardware: step 2a check and step 8 |

### LOG-14: chain verifier
| Clause | Tests |
| --- | --- |
| Verifies a set of session files as one chain | `LOG_14_session_142_example_verifies`, `LOG_14_two_sessions_verify_as_one_chain`, `LOG_2_parts_are_checked_in_order_with_continuing_record_numbers` |
| Reports the first broken or missing record | `LOG_14_changed_record_is_named`, `LOG_14_deleted_record_is_named_as_missing`, `LOG_14_deleted_session_file_breaks_the_chain` |
| An incomplete last line is truncated, not broken | `LOG_14_truncated_last_line_is_reported_not_broken` |
| Continues from the laptop's last hash | `LOG_14_laptop_last_hash_must_be_continued` |
| Command line: exit codes and JSON | `LOG_14_cli_exit_codes_and_json` |
