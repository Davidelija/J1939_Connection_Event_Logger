# Design change log

Every change to the design made during development is recorded here, in order. The baseline is the specification as of the Nov 10, 2026 cut-over: the requirements, hand-off (decisions X1 to X42 in its decision log), log format, module contracts (`docs/modules.md`) and error table. Entries continue from DC-1.

Read this file at the start of every session, after `CLAUDE.md`.

## Rules

1. **No silent deviations.** Any code that departs from the requirements, a module contract, the log format or the error table needs an entry here first. Claude Code may write the entry as **proposed**; it does not build on a proposed change. It either works on something else or stops and asks.
2. **Who approves.** A project member (Vaughan Lynn or Elijah Umaru) changes the status to **accepted** or **rejected**, with their name and the date. Claude Code never accepts its own proposal.
3. **Specs change in the same pull request.** When an entry is accepted, the affected documents are edited in the same change as the code, so the specs always describe the current design. This log records what moved and why; it does not replace the specs.
4. **Contracts are versioned.** A change to a module's inputs, outputs, errors or config keys raises that module's contract version in `docs/modules.md` and names it here.
5. **Formats.** A change to a record, field or file format follows `CLAUDE.md` rule 7 (update `docs/log-format.md` first, raise the format version once a release has shipped, add a format history line).
6. **Nothing is deleted.** Rejected and superseded entries stay, so the same idea is not proposed twice. A later entry that replaces an earlier one says "supersedes DC-n".
7. **Open questions** are proposed entries with "Question:" in the change line, so there is one place to look.
8. **Releases.** Each tagged release's `CHANGELOG.md` entry lists the DC entries it includes.
9. **Parallel sessions.** A proposed entry takes a provisional ID, `DC-new-<yyyymmdd>-<topic>`, so two sessions never collide; the next free number is assigned when it is accepted and merged. Each session works on its own branch (one per build step or module) and claims it in the pull request title.

## Entry template

```markdown
## DC-n — <short title>  (proposed | accepted | rejected | superseded by DC-m), <date>
- **Raised by:** <person, or Claude Code with the build step and pull request>
- **Decided by:** <name, date> (blank while proposed)
- **Change:** <what is different from the baseline or the last entry>
- **Why:** <the evidence or reason: a test result, a bench measurement, a review finding>
- **Affects:** <requirement IDs; modules and their new contract versions; config keys; record types; files>
- **Docs updated in the same change:** <requirements.md, modules.md, log-format.md, errors.md, user-manual.md, ...>
- **Tests:** <tests added or changed, named by requirement ID>
```

## Entries

## DC-19 — A corrupt device library is a high fault; identification continues without it  (accepted, 2026-11-14)
- **Raised by:** Claude Code, step 5 PR 2 (session wiring), branch `step-5-session`
- **Decided by:** Vaughan Lynn, 2026-11-14 ("high fault, identify without it", chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** `session` loads the newest device library on the card (`library/lib-vN.json`, through `store`) at power-on and records its version in `session_start` (IDN-5). A missing library means no library matches. A library that fails `lib-1` validation gives a high `fault` "device library corrupt (reasons)" with logger action "identifying without it" in the first session; the logger keeps recording and identifies from NAME and self-reported replies only. `docs/errors.md` adds the case to the corrupt-file row.
- **Why:** `docs/errors.md` covered a corrupt inventory or config, not the library. Detection does not depend on the library, so the logger keeps recording, and the fault is high so the operator sees it, as for a corrupt inventory.
- **Affects:** IDN-5; `session` (library loading, contract text); `docs/errors.md` (Storage, corrupt file row). No record change; format stays `log-1`.
- **Docs updated in the same change:** `docs/errors.md`, `docs/modules.md`, `CHANGELOG.md`.
- **Tests:** `test_IDN_5_corrupt_library_is_a_high_fault_and_identification_continues`.

## DC-18 — Trailer devices are classified by the rule "NAME"  (accepted, 2026-11-14)
- **Raised by:** Claude Code, step 5 PR 1 (`identify`), branch `step-5-identify`
- **Decided by:** Vaughan Lynn, 2026-11-14 ("NAME", amend the note, chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** the requirements' Classification rule enumeration said "NAME is used in analysis only", but DET-18 classifies a trailer device from its NAME and DC-17 records that as rule "NAME". The note now reads: the logger writes NAME only for the trailer rule (DET-18); otherwise NAME is used in analysis only. `identify.classify` and `identify.reclassify` (a trailer claiming a known ECU's address) write "NAME".
- **Why:** the requirement and the enumeration note disagreed; the requirements win, and DET-18 is the requirement that needs the value.
- **Affects:** DET-18; `docs/requirements.md` (Enumerated values: Classification rule). `types.CLASSIFICATION_RULES` already holds "NAME". Format stays `log-1`.
- **Docs updated in the same change:** `docs/requirements.md`, `CHANGELOG.md`.
- **Tests:** `test_DET_18_trailer_name_is_a_trailer_device_at_notice`.

## DC-17 — Step 5 freeze: confidence, self-reported identity, make and profile fields, ties, classification rules, inputs  (accepted, 2026-11-14)
- **Raised by:** Claude Code, step 5 freeze, branch `step-5-freeze`
- **Decided by:** Vaughan Lynn, 2026-11-14 (all ten items accepted in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** how `identify` fills the parts of IDN-3, IDN-4, DET-13 and DET-18 that the specs left open:
  1. **Confidence (IDN-3).** The base is the number of identification sources that agree: three (NAME, self-reported reply, request pattern) is high, two is medium, one is low. A source counts when it contributes: NAME when the matched entry's function gate is non-empty and passed, or a rule decided the category from the NAME; self-reported reply when a reply gave a make or model; request pattern when a library entry scored above 0. The IDN-3 and IDN-4 one-step reductions then apply, never below low. The session 142 example (NAME and request pattern, medium) follows this.
  2. **Self-reported identity (IDN-3).** Replies are ASCII fields separated by `*`. Component ID (65259): make is field 1, model is field 2. ECU ID (64965): make is field 5. Software ID (65242): no make or model; its first byte (the field count) is dropped. In the record, each request's `value` is the reply text without its trailing `*`.
  3. **Make without a source.** `make` is "unknown (mfr code N; no manufacturer list loaded)" when the list is empty, or "unknown (mfr code N not in the list)" when it is loaded, with `make_source` "none", as in the example.
  4. **Library-only make or model (IDN-4).** `make` and `model` hold the entry's values, `make_source` is "library", and a new field `profile_match` says "matches <make> <model> profile"; `profile_match` is null otherwise.
  5. **Disagreeing sources (IDN-3).** When two sources give different makes or models, the record uses the first by precedence and a new field `disagreements` lists every source's value as `{"source", "make", "model"}`; empty when they agree.
  6. **Type ties (IDN-4).** The broader category is the part of the tied types before the first comma when they share it ("diagnostic tool"), else "external device". The tied types go in a new field `candidates` (null when there is no tie). A type is guessed only when the best entry scores above 0; otherwise `type_guess` is null. Source-address hints (249, 250) break an exact tie only.
  7. **When identification runs.** `session` calls `identify` when all three identity requests for a connection have an outcome (NP-13), with `monitor`'s requested-PGN set at that moment; and again at connection end. `monitor` v1.2 adds `requested_pgns(conn)`, the distinct PGNs the connection has requested (bounded by `limits.pgns_per_conn`). Devices with a known NAME are not asked (NP-13), so approved devices get no `identification`.
  8. **Classification rules at connection start (DET-13, DET-18).** `identify` provides `classify(name, since_first_frame_s)`, which `detect` takes as an injected function from `session` (the two are independent siblings in the layers): trailer device (notice, rule "NAME") when the NAME's industry group is 1 (on-highway) and its vehicle system is `classify.trailer_vehicle_system`; else wake timing as now.
  9. **Reclassification (DET-13, DET-18(c)).** A vehicle ECU not in baseline or a trailer device that sends a diagnostic request (any Request other than for Address Claim), a control PGN, DM14 to DM18, or (trailer only) claims an address held this session by a known NAME or an inventory ECU's address, becomes "external device (unrecognized)", high. A not-in-baseline ECU whose connection ends before the session does becomes external at its end. The change and its reason go in the `identification` record (`category`, `classification_rule` "request activity" or "wake timing", `reclassified` with the reason), or in `final_identification` when it happens later; `connection_end` takes the final severity.
  10. **X15 rig check.** The DET-13 request-rule check against rig captures (handoff open check) needs the rig captures and is recorded by Vaughan or Elijah; the code keeps the rule as written until then.
- **Why:** gaps found while freezing the step 5 contracts.
- **Affects:** DET-13, DET-18, IDN-3, IDN-4; `identify` v1 (frozen with these rules), `monitor` v1.2 (`requested_pgns`), `detect` v1.2 (injected `classify`), `session`; `docs/log-format.md` (`identification` gains `profile_match`, `disagreements`, `candidates`, `category`, `classification_rule`, `reclassified`; `final_identification` the same). No release has shipped, so the format stays `log-1`.
- **Docs updated in the same change:** `docs/modules.md`, `docs/log-format.md`, `CHANGELOG.md`.
- **Tests:** written with the step 5 code (`test_DET_13_*`, `test_DET_18_*`, `test_IDN_3_*`, `test_IDN_4_*`, `test_IDN_6_*`).

## DC-16 — Acknowledgments to the logger are replies to it; monitor and detect interfaces named  (accepted, 2026-11-14)
- **Raised by:** Claude Code, step 4 PRs #14, #15 and #16 (gaps: PR #16 gap 3, PR #14 gap 2, PR #15 gap 1)
- **Decided by:** Vaughan Lynn, 2026-11-14 ("mark in decode" and "name them in the contracts", chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:**
  1. `decode` v3: `J1939Msg.reply_to_logger` is also true for an Acknowledgment (59392) whose address byte (byte 5) is the logger's address. J1939 sends a NACK or ACK to global, so before this change a vehicle ECU's NACK to one of the logger's own requests reached `detect` and `monitor` and could be logged as `known_device_new_pgn`. `requests` still reads these NACKs for its outcomes; it does not filter on `reply_to_logger`.
  2. `monitor` v1.1 and `detect` v1.1: the public methods already built in step 4 are named in `docs/modules.md` (constructor, `on_message`, `summary`, `end`, the test seams `open_transfers` and `table_sizes`; `poll`, `sweep_complete`, `no_sweep`, `waiting`, `end_all`, `connections`, `connection_for`, `entry_for`, `name_at`). `monitor`'s rule that an address claim is never a new PGN (step 4 PR 3) is written into its contract. No behaviour change.
- **Why:** NP-15 excludes replies to the logger from detection, and a NACK answering the logger is such a reply even though it is addressed to global. The step 4 methods were the contracts' inputs and outputs but were not named.
- **Affects:** NP-15, DET-12; `decode` v3, `monitor` v1.1, `detect` v1.1 in `docs/modules.md`. No record or format change; format stays `log-1`.
- **Docs updated in the same change:** `docs/modules.md`, `docs/module-map.md`, `CHANGELOG.md`.
- **Tests:** `test_NP_15_ack_naming_the_logger_is_a_reply_to_it`, `test_NP_15_ack_naming_another_address_is_not`, `test_NP_15_ecu_nack_to_the_logger_is_not_a_new_pgn`; `test_SC_6_monitor_public_names`, `test_SC_6_detect_public_names` extended.

## DC-15 — PGNs sent count the carried PGN, not TP.CM and TP.DT  (accepted, 2026-11-14)
- **Raised by:** Claude Code, step 4 PR 1 (`monitor`), pull request #14 (gap 1)
- **Decided by:** Vaughan Lynn, 2026-11-14 ("fix the example", chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** `connection_end.pgns_sent` counts the PGN each message carries. A transport-protocol transfer counts once, as its reassembled PGN; TP.CM (60416) and TP.DT (60160) frames are not counted, because `decode` v2 does not return them as messages. In the session 142 example, rec 9 loses its TP.CM and TP.DT rows and gains `pgns_dropped: 0` (DC-13). The chain is recomputed from rec 9, and the `retrieval` record's `last_hash` follows it.
- **Why:** the example listed TP.CM and TP.DT counts that no module produces. DET-7 asks for "each distinct PGN it sends", which is the carried PGN. Keeping `decode` as it is avoids a decode contract change and transport frames reaching `detect` and `monitor`.
- **Affects:** DET-7; `docs/log-format.md` (`connection_end` PGNs sent); `docs/examples/s000142_20261106T140211Z.jsonl` (rec 9; chain from rec 9). No contract change. Format stays `log-1`.
- **Docs updated in the same change:** the files above; `CHANGELOG.md`.
- **Tests:** `test_DET_7_summary_matches_the_example_connection_end_fields`, `test_LOG_5_example_session_142_hash_chain_verifies`.

## DC-14 — Monitor record fields: control_flag `via` and `raw_capture`, connection_end list entries  (accepted, 2026-11-14)
- **Raised by:** Claude Code, step 4 PR 1 (`monitor`), branch `step-4-monitor`
- **Decided by:** Vaughan Lynn, 2026-11-14 (all seven items accepted in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** how the monitor fills the fields that DC-13 and `docs/log-format.md` list but did not spell out:
  1. `control_flag.via` (the field name in the session 142 example) takes DC-13's values: "single frame", "transport (BAM)", "transport (RTS/CTS)" or "requested". The example's `"via": "Request 59904"` becomes `"requested"`; the example chain is recomputed, as in DC-7.
  2. `control_flag.raw_capture` is null until `rawcap` exists (step 6), and afterwards whenever no capture was written (for example, `limits.raw_mb_per_session` used up).
  3. Each `requests_first_100` item is `"<pgn> <name> -> SA <n>"` or `"<pgn> <name> -> global"`, with the name left out for a PGN not in the logger's own short name table. The list holds up to `detection.requests_kept` items and carries no "...N more" item; the example's last item is shortened for the illustration only. `requests_dropped` counts the rest.
  4. `etp_transfers` items: `{"sender", "destination", "pgn", "bytes", "result": "completed" | "aborted", "memory_transfer"}`. A transfer still open at connection end is reported as "aborted".
  5. `new_pgns` items: `{"pgn", "name", "direction": "sent" | "requested"}`; `known_device_new_pgn` carries the same `direction` field.
  6. `pgns_dropped` counts messages whose PGN was not added to the table because the table already held `limits.pgns_per_conn` PGNs.
  7. `ecus_contacted` lists, in ascending order, every destination of a destination-specific message from the connection (not 255, and not the logger, by NP-15).
- **Why:** these values are needed to write `monitor.summary()` and `control_flag`. DC-13 named the values but not the field shapes, and `rawcap` comes later than step 4.
- **Affects:** DET-7 to DET-12; `monitor` v1 (no contract change: outputs as listed); `docs/log-format.md` (`control_flag`, `connection_end`, `known_device_new_pgn` field detail); `docs/examples/s000142_20261106T140211Z.jsonl` (rec 8 `via`; chain recomputed). Format stays `log-1`.
- **Docs updated in the same change:** `docs/log-format.md`, the session 142 example, `CHANGELOG.md`.
- **Tests:** `test_DET_7_*` to `test_DET_12_*` in `tests/unit/test_monitor.py`; Hypothesis on `monitor` (SC-12a).

## DC-13 — Step 4 freeze: connection_end writer, DET-3 connections, DET-5 evidence, ETP tracking, inventory input, control-flag fields, known-device new PGNs, silence end, moves, input limits  (accepted, 2026-11-14)
- **Raised by:** Claude Code, step 4 freeze pull request #13 (gaps 1 to 10)
- **Decided by:** Vaughan Lynn, 2026-11-14 (accepted in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:**
  1. `detect` writes `connection_end` and takes the activity fields from `monitor.summary(conn)`.
  2. DET-3: a destination-specific message to an address no claimed NAME holds (not 254, 255, the logger's or a never-claiming inventory address) opens a connection keyed by that SA, trigger "replies sent to SA N".
  3. DET-5: the `sweep` record from `requests` (NAMEs added and missing) is the evidence; `detect` uses the sweep only for the first-sweep wait.
  4. `monitor` follows ETP from ETP.CM messages and records sender, destination, PGN, bytes, completed or aborted, and the memory-transfer flag.
  5. `detect` and `monitor` take `config.Inventory` (addresses, PGNs sent, approved PGNs, trained requests); step 1's `detect.InventoryEntry` is retired.
  6. `control_flag`: "how it was sent" is single frame, transport (BAM), transport (RTS/CTS) or requested; `target_sa` null for global; first occurrence per connection and PGN, running count in `connection_end`.
  7. `known_device_new_pgn`: once per session per NAME (or SA), PGN and direction, count 1; behind `detection.known_device_new_pgn`.
  8. DET-6: "silence" after `detection.silence_end_s` without frames from the connection while others arrive; key-off ends every open connection with "key-off".
  9. DET-4 moves and same-NAME conflicts as in X42: `address_change` after `detection.move_grace_s` of silence at the old address (info, or notice for another known ECU's address), once per NAME and address; old address still sending or both answering a sweep gives `address_conflict` "same NAME at two addresses", high.
  10. DET-8, DET-19: `pgns_dropped` after `limits.pgns_per_conn` distinct PGNs; `requests_dropped` after `detection.requests_kept`.
- **Why:** gaps found while freezing the step 4 contracts (pull request #13).
- **Affects:** `docs/modules.md` (`detect` and `monitor` rules; no version change: the outputs are those already listed, now defined); `docs/log-format.md` (`control_flag` values, `connection_end.pgns_dropped`); `session` passes `config.Inventory`. Format stays `log-1`.
- **Docs updated in the same change:** the files above; `CHANGELOG.md`.
- **Tests:** written with the step 4 code (`test_DET_*`), plus Hypothesis on `monitor` (SC-12a).

## DC-12 — Step 3 freeze: transfer replies, send handle, bit rate, rate cap, outstanding requests, breach rules, bus state, restart guard, VIN check, address choice  (accepted, 2026-11-13)
- **Raised by:** Claude Code, step 3 freeze pull request #9 (gaps 1 to 10)
- **Decided by:** Vaughan Lynn, 2026-11-13 (accepted in the Claude Code session, option B for the VIN; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:**
  1. `decode` v2 produces CTS and EOMA (as well as Connection Abort) `TxRequest`s for transfers addressed to the logger.
  2. `capture` v2 gives `transmit`, and only `transmit`, a send handle on its own socket (`transmit_handle()`), so the logger's frames keep `MSG_CONFIRM` and `Frame.own` stays exact; capture never sends.
  3. `session` stays listen-only until `platform.bitrate_check()` confirms 250000 or 500000, retrying, with a fault after `can.bitrate_fault_s`; then `capture.set_mode(listen_only=False)`.
  4. Rate cap: at most `transmit.max_frames_per_s` frames in any sliding 1 s window, all frames counted; protocol frames go first; a frame over the cap waits.
  5. Outstanding requests: `transmit` holds a second request to a destination until `requests` calls `release(da)`; global requests count as destination 255.
  6. Breach: a PGN outside `transmit.allow_list`; a Request for a PGN outside `requests.allow_list`; an Address Claim with another NAME; an Acknowledgment that is not a NACK; a TP.CM that is not CTS, EOMA or Abort; a kind that does not match its PGN. Refused, never sent; transmit off for the session with a high `tx_breach` fault.
  7. `decode.bus_state(frame)` reads bus-off and TX error-passive from error frames; `session` calls `transmit.disable(reason)` on either, and `transmit` disables itself on `ENOBUFS`.
  8. Restart guard: `state.json` gains `unclean_starts` (UTC times, or null); the guard holds when `restart_guard.count` fall within `restart_guard.window_min`; it clears after a clean end or an operator `restart`.
  9. VIN, option B: `session_start` at ready has `vin` null and `vin_status` "pending"; a new `vin_check` record (info) follows with the VIN, its status, the inventory VIN and the request outcome. `vin_mismatch` stays the high record for a mismatch (step 6).
  10. Address choice from `address.claim_from` down, skipping inventory, claimed and reserved addresses; lower NAME wins; wait `address.claim_wait_ms`; Cannot Claim from 254 after the last loss; answer Request for Address Claim, NACK other requests to the logger, ignore Commanded Address.
- **Why:** gaps found while freezing the step 3 contracts (pull request #9).
- **Affects:** `decode` v1 to v2, `capture` v1 to v2 (`docs/modules.md`); `transmit`, `address`, `session` wording; `docs/log-format.md` (`vin_check` record; `unclean_starts` in `state.json`); `docs/requirements.md` (VIN status "pending"). Formats stay `log-1` and `state-1` (no release has shipped).
- **Docs updated in the same change:** the files above; `CHANGELOG.md`.
- **Tests:** written with the step 3 code (`test_NP_*`), including the witness checks on `vcan0`.

## DC-11 — Record numbers continue across parts; session_start keeps every field from step 2  (accepted, 2026-11-13)
- **Raised by:** Claude Code, build step 2 PR 2 (branch `step-2-session`)
- **Decided by:** Vaughan Lynn, 2026-11-13 (chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:**
  1. `rec` counts within the session, not the file: it continues across parts, so event IDs (session and record number) stay unique after a roll-over.
  2. From step 2, `session_start` carries every field in `docs/log-format.md`. Values built in later steps are written as placeholders until then: `vin` null with `vin_status` "unavailable", `logger_sa` null, `logger_claim` "not claimed (transmit starts in step 3)", `restart_guard` "not checked (step 3)", `operator_keys` from the keys folder (empty until step 7), `bitrate_check` saying the bit rate came from the platform until step 3 confirms it from frames.
  3. The two `session_start` fields that log-format names but the example does not show are written as `prev_end_cause` (the cause from the diagnostic log, or null) and `bytes_cut_off` (bytes of an incomplete last line after a power loss, or 0).
- **Why:** `rec` "within the session file" would reuse event IDs in every part; a fixed header layout from step 2 keeps later steps from changing the record shape.
- **Affects:** `docs/log-format.md` (`rec`); `session`, `eventlog`. Format stays `log-1` (no release has shipped).
- **Docs updated in the same change:** `docs/log-format.md`, `CHANGELOG.md`.
- **Tests:** `test_LOG_2_*` (rec across parts), `test_LOG_6_*` (header fields).

## DC-10 — Step 2 freeze: time without a clock, vehicle time, state.json, parts, previous-session end, diagnostic log  (accepted, 2026-11-13)
- **Raised by:** Claude Code, step 2 freeze pull request #5 (gaps 1 to 10)
- **Decided by:** Vaughan Lynn, 2026-11-13 (accepted in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:**
  1. With no valid time (`clock_source` `elapsed`), records have null `utc` and `written` and carry `elapsed_s` (seconds since wake, milliseconds); the session file is named `s<NNNNNN>_noclock.jsonl` when no valid time exists at session start.
  2. `clock` v2 adds `veh_time(ts_mono)` (vehicle time from the Time/Date offset, whole seconds, None before the first reply) and `elapsed_s(ts_mono)`.
  3. `session` writes `session_end.frames_not_j1939` with the log-format keys, mapping `DecodeStats.non_j1939["standard"]` to `std_11bit`.
  4. `state.json` layout `state-1`: `format`, `logger_id` (the logger NAME), `session` (last session number), `last_hash`.
  5. The manufacturer list is part of the device library file (IDN-2); `store` has no separate kind for it.
  6. The diagnostic log (LOG-20) is written by a minimal `admin` built in step 2 (`diag/logger.log`, rotated by `diag.max_bytes` and `diag.files`); the rest of `admin` comes in step 7.
  7. Previous session end: clean if the newest session file ends with `session_end`; otherwise the diagnostic log's last restart cause (software restart, watchdog restart); otherwise power loss, with the bytes cut off equal to any incomplete last line.
  8. After a crash the last complete line of the newest session file gives the last hash and wins over `state.json`; `state.json` is used only in the LOG-5 cases without session files.
  9. Roll-over: the closing part ends with `session_end` (reason "session roll-over"); the next part (`_p2.jsonl`, ...) starts with a repeated `session_start` with the same session number and `part` + 1; the chain continues.
  10. After key-off the logger waits listen-only and starts a new session (wake cause "CAN activity") on the next frame (sleep stays deferred, HW-5).
- **Why:** gaps found while freezing the step 2 contracts (pull request #5).
- **Affects:** `docs/log-format.md` (`utc`, `elapsed_s`, file names, parts, `state.json`; format history: `state-1` added, `log-1` unchanged as no release has shipped); `docs/modules.md` (`clock` v1 to v2; wording in `eventlog`, `store`, `session`, `admin` and §2); `docs/handoff.md` (step 2 scope).
- **Docs updated in the same change:** the files above; `CHANGELOG.md`.
- **Tests:** written with the step 2 code: `test_LOG_16_*` (elapsed mode, `veh_time`), `test_LOG_5_*` (`state.json`, crash recovery), `test_LOG_2_*` (parts), `test_LOG_12_*` and `test_LOG_18_*` (previous end), `test_LOG_20_*` (diagnostic log), `test_LOG_17_*` (key-off and next session).

## DC-9 — Step 1 runs the pipeline with a minimal session, a wake-timing category and the config file read directly  (accepted, 2026-11-13)
- **Raised by:** Claude Code, build step 1 PR 2 (branch `step-1-logic`)
- **Decided by:** Vaughan Lynn, 2026-11-13 (chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:**
  1. Step 1 includes a minimal `session`: a main loop that runs capture, decode, clock, detect and eventlog, and syncs at once after a `connection_start` (DET-16). The rest of `session` (header, end record, parts, roll-over, `state.json`, self-check, watchdog, restart guard) is built against its frozen contract in step 2.
  2. Step 1's minimal `detect`: an address claim by a NAME that is not in the inventory opens a connection and writes `connection_start` with `classification_rule` "wake timing": a first claim within `classify.wake_window_s` of the session's first frame gives "vehicle ECU not in baseline", a later one "external device (unrecognized)", both high. With no inventory the session is untrained and severity is capped at notice (TRN-9). An approved external device in the inventory gets an info `connection_start` in the short form (NAME and entry ID). Baseline ECUs get none. `identify` takes over classification in step 5; the rest of `detect` comes in step 4.
  3. Step 1 reads the settings it needs straight from the config file (cfg-1 JSON), without validation, in the entry point; the `config` module replaces this in step 2. The inventory's NAMEs, entry IDs and categories are read the same way until step 6.
- **Why:** the step 1 gate (a replayed new claim gives a chained `connection_start` within 2 s) needs a loop, a category and settings, and the modules that own them (`session`, `identify`, `config`, `inventory`) come in later steps.
- **Affects:** build plan step 1 scope (`docs/handoff.md`); `session`, `detect` and `main` exist in minimal form before their contracts freeze; no contract version changes.
- **Docs updated in the same change:** `docs/handoff.md` (build plan, step 1 scope), `CHANGELOG.md`.
- **Tests:** `test_DET_1_*`, `test_DET_16_*` (including the `vcan0` end-to-end check).

## DC-8 — Step 1 freeze: defined outputs for capture and decode, TxRequest in the shared types, eventlog's step 1 scope  (accepted, 2026-11-13)
- **Raised by:** Claude Code, step 1 freeze pull request #3 (gaps 1 to 6)
- **Decided by:** Vaughan Lynn, 2026-11-13 (accepted in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** before the step 1 contracts freeze, outputs that were named but not defined are defined:
  1. `CaptureStats`: `kernel_drops: int`, `rx_buffer_bytes: int`, `frames: dict[str, int]` (keys `extended`, `standard`, `remote`, `error`).
  2. `DecodeStats`: `non_j1939: dict[str, int]` (keys `standard`, `remote`, `error`), `tp_closed: dict[str, int]` and `malformed: dict[str, int]` (by reason), `etp_seen: int`. Decode's state is a `DecodeState` that only `decode` reads or changes.
  3. `TxRequest(pgn, da, data, kind)` moves, unchanged, from the `transmit` contract into the shared types (§1), so the frozen `decode` contract does not depend on `transmit`, which freezes in step 3.
  4. `eventlog`'s step 1 freeze ("append only") covers appending a `Record`, the hash rule, one `write()` per record with `O_APPEND`, `sync_now()` and the last hash; session parts, roll-over and crash recovery freeze in step 2.
  5. `capture.read_batch(max_n)` never waits: it returns the frames already in the ring, up to `max_n`, oldest first.
  6. `capture.window(start_mono, end_mono)` includes frames at both ends.
- **Why:** the step 1 contracts are frozen so tests can be written against them; these outputs had names but no fields, and `decode` depended on a type in an unfrozen contract.
- **Affects:** `docs/modules.md` §1 (`TxRequest`), `capture`, `decode`, `transmit` (input wording only) and `eventlog`. These contracts were not yet frozen, so their versions stay v1. `types.py` gains `TxRequest` and `TX_KINDS`.
- **Docs updated in the same change:** `docs/modules.md`, `CHANGELOG.md`.
- **Tests:** `test_SC_6_types_exports_exactly_the_contract_names`, `test_SC_6_shared_type_fields_match_the_contract` (now including `TxRequest`). `CaptureStats`, `DecodeStats` and `DecodeState` are tested with `capture` and `decode` in step 1 PR 2.

## DC-7 — Example files use the enumerated values; approval kind "inventory"  (accepted, 2026-11-13)
- **Raised by:** Claude Code, build step 1, pull request #2 (item 7, parts b and c)
- **Decided by:** Vaughan Lynn, 2026-11-13 (chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:**
  - (b) Record fields that take an Enumerated value hold exactly that value; detail goes in its own field. In the session 142 example: the Component ID request outcome "no reply after 1 retry" becomes "no reply" (NP-14 already means one retry); `classification_rule` "wake timing (first claim 29 min after the session's first frame)" becomes "wake timing", with the detail in a new `classification_detail` field on `connection_start`; `id_source` becomes a list of Identification source values, `["NAME", "request pattern"]` (the function code and library version are already in the record's NAME fields and the session header). In `inv-v2.json` an approved PGN's `kind` "sent" becomes "PGN sent". The session file's hash chain is recomputed from record 5, and the `retrieval` record's `last_hash` follows it.
  - (c) The requirements' Approval kind enum gains "inventory" (confirming a trained inventory), which `docs/log-format.md` already lists for the `approval` record.
- **Why:** the example is the worked reference for every record; values that differ from the enums would be copied into code and tests. A confirmed training needs an approval kind.
- **Affects:** `docs/requirements.md` (Enumerated values: Identification source, Approval kind); `docs/log-format.md` (`connection_start` gains `classification_detail`; `identification` `id_source` is a list); `types.py` (`APPROVAL_KINDS`); `docs/examples/s000142_20261106T140211Z.jsonl`, `docs/examples/inv-v2.json`. No release has shipped, so the formats stay `log-1` and `inv-1` (as X16, X28, X42).
- **Docs updated in the same change:** the files above; `CHANGELOG.md`.
- **Tests:** `test_LOG_5_example_session_142_hash_chain_verifies`, `test_LOG_5_example_retrieval_last_hash_is_the_chain_before_it`, `test_IDN_6_example_values_use_the_requirements_enumerations`, `test_TRN_13_example_inventory_approval_kinds_use_the_enumeration`.

## DC-6 — Step 1 interface clarifications  (accepted, 2026-11-13)
- **Raised by:** Claude Code, build step 1, pull request #2 ("[step 1 | interfaces] ...")
- **Decided by:** Vaughan Lynn, 2026-11-13 (chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** ten points the step 1 interface code exposed, each settled as follows:
  1. `Paths(card, flash, keys)` is defined in `platform/interface.py`, not in the shared types.
  2. Platform `now()` reports `rtc`, or `elapsed` with no wall time; only `clock` reports `vehicle`, from its own offset.
  3. `capture` sets the CAN receive buffer (`SO_RCVBUFFORCE`, `can.rx_buffer_bytes`) and reads it back; `open_can()` does not.
  4. Switching from listen-only to normal mode (NP-2): `capture` closes the socket and calls `open_can(listen_only=False)`. No new platform function. Any receive gap is measured in step 3.
  5. Dev tools are pinned by version in `pyproject.toml` and by hash in `requirements/dev.txt`.
  6. Enumerated values: a note in parentheses that names a config key, a synonym or a scope is not part of the value ("silence", "power loss", "needs training", "NAME"); the Category values keep their parentheses.
  7. `types.py` writes optional fields as `Optional[X]` (DC-1), because the shared types are evaluated at run time.
  8. Tests of project tooling start with the DC ID that defines the tool (`test_DC_2_...`) instead of a requirement ID.
  9. SC-2 stays at step 3; the step 1 `capture` test covers the reading side early.
  10. A bad argument to a platform function (an unknown light pattern or `fault()` operation) is a programming error and raises `ValueError`, not `PlatformError`.
- **Why:** gaps and disagreements between the specs found while writing the interface code (pull request #2, items 2 to 11).
- **Affects:** platform contract (wording only; the version change is DC-5); `capture` contract (buffer and mode change; wording, no version change); enumerations in `types.py`.
- **Docs updated in the same change:** `docs/modules.md` (§1, §4 platform and capture), `docs/porting.md` §3, `docs/requirements.md` (Enumerated values), `docs/test-plan.md` §2, §3 and §10, `docs/handoff.md` (Testing: Naming; Ground rules 3), `CLAUDE.md` rule 3.
- **Not decided here:** the session 142 example's spellings and approval kind "inventory"; both decided in DC-7.
- **Tests:** `test_SC_6_*` contract tests; `test_STS_1_set_light_rejects_unknown_pattern`; `test_PLT_2_fault_rejects_unknown_operation`; `test_DC_2_*`.

## DC-5 — Platform `fault(op)` for socket and storage fault injection  (accepted, 2026-11-13)
- **Raised by:** Claude Code, build step 1, pull request #2, as the question DC-new-20261113-fault-delivery
- **Decided by:** Vaughan Lynn, 2026-11-13 (option B; chosen in the Claude Code session; recorded by Claude Code, to be confirmed in the pull request review)
- **Change:** the platform contract goes from v1 to v2 with a ninth function, `fault(op: str) -> None`. Layer 1 modules call it just before each operation in `FAULT_OPS`: `can_recv` (`capture`), `can_send` (`transmit`), `card_write` (`eventlog`, `store`, `rawcap`), `card_sync` (`eventlog`, `store`) and `flash_write` (`store`). `DesktopPlatform` raises `PlatformError(kind)` while a planned fault is active for that operation: `can_down` (`can_recv`, `can_send`), `enobufs` (`can_send`), `enospc`, `erofs` (`card_write`), `eio`, `card_removed` (`card_write`, `card_sync`), `state_unwritable` (`flash_write`); `slow_sync` delays `card_sync` by `args["s"]` seconds instead of raising. `args["ops"]` narrows a kind to some of its operations. Hardware implementations do nothing in `fault()`.
  Fault-plan semantics (all kinds the plan delivers): a fault is active from `at_mono` for `args["for_s"]` seconds, or for the rest of the run; `clock_jump` steps wall time by `args["s"]` when monotonic time reaches `at_mono`. The plan also delivers `can_missing` (`open_can()`), `no_bitrate` (`bitrate_check()` returns None) and `rtc_invalid` (`rtc_ok()` False, `now()` source `elapsed`).
- **Why:** the fault plan must inject the socket and storage errors in `docs/errors.md`, which are detected in modules that otherwise never call the platform. Of the options raised (A: route all I/O through the platform; B: one `fault(op)` hook; C: inject by harness and traffic only), B keeps the platform small and leaves real I/O in the layer 1 modules.
- **Not covered:** the other 35 kinds (bus traffic such as `bus_off`, `bad_frame`, `tp_error`, `claim_change`; file contents such as `truncated_line`, `corrupt_file`, `state_corrupt`; service events `exception`, `hang`, `restart_loop`; `rx_overflow`; vehicle time; `card_nearly_full`; and the command, laptop and install kinds). A plan naming one of them raises `NotImplementedError`. How each is injected (traffic, harness or test setup) is still to be decided, kind by kind, as its build step lands.
- **Affects:** platform contract v1 to v2 (`docs/modules.md` §4); `capture`, `transmit`, `eventlog`, `store` and `rawcap` call `platform.fault()` (a rule in each contract; their inputs, outputs and errors are unchanged, so their versions stay v1); `docs/modules.md` §5 (injection points); `docs/test-plan.md` §3 and §4; `docs/porting.md` §3.
- **Docs updated in the same change:** `docs/modules.md`, `docs/porting.md`, `docs/test-plan.md`.
- **Tests:** `test_PLT_2_fault_op_raises_each_planned_kind_on_its_operations`, `test_LOG_22_card_removed_fault_window_ends_after_for_s`, `test_LOG_22_fault_ops_arg_narrows_the_operations`, `test_LOG_3_slow_sync_fault_delays_card_sync_by_s`, `test_LOG_5_state_unwritable_fault_hits_flash_only`, `test_PLT_2_fault_plan_refuses_kinds_without_a_delivery_path`, `test_SC_6_platform_protocol_has_exactly_the_nine_functions`.

## DC-4 — Ownership of the test harness, component and replay tests and bench procedures  (accepted, 2026-11-09)
- **Raised by:** Claude, test plan review (test plan v2)
- **Decided by:** Vaughan Lynn, 2026-11-09
- **Change:** test-script writers also own `tools/fixtures/` (including `scenario.py`), `tests/harness/`, `tests/component/` (level 2, including its fixture runner), `tests/replay/` (level 3), `bench/` procedures and `bench/checklists.md`. Developers keep `src/`, unit tests and contract tests (`tests/contract/`). `scenario.py` writes the fixture folder (`traffic.log`, `manifest.json`) and the findings ground-truth file (`docs/findings-data/scenarios/<scenario>.json`) from one description. The pull request template adds: "affected fixtures, manifests and test-plan cases updated".
- **Why:** `docs/modules.md` §5 named only fixtures, manifests and `tools/findings/` for the test side; the harness, replay tests and bench procedures had no stated owner.
- **Affects:** `docs/modules.md` §5 (no contract version change); `.github/pull_request_template.md`; the repository layout.
- **Docs updated in the same change:** `docs/modules.md`, `.github/pull_request_template.md`, `docs/handoff.md` (repository layout, Testing), `CLAUDE.md` (Environment), `docs/test-plan.md` §2 and §3.
- **Tests:** none.

## DC-3 — Verify IDN-4 by test as well as analysis  (accepted, 2026-11-09)
- **Raised by:** Claude, test plan review (test plan v2)
- **Decided by:** Vaughan Lynn, 2026-11-09
- **Change:** IDN-4's verification method changes from A to T, A. Not-deferred T requirements become 95.
- **Why:** the score is exactly defined (function-code gate, Jaccard, never-PGN penalty, floor, tie margin, recalculation at connection end), so known-answer tests can check it; as A only, the coverage check did not require them.
- **Affects:** IDN-4; `docs/verification.md` row (Step 5).
- **Docs updated in the same change:** `docs/requirements.md` (IDN-4 Verify column), `docs/verification.md`, `docs/test-plan.md` §10.
- **Tests:** `test_IDN_4_*` unit known answers (including session 142: code reader 0.60, service tool 0.40 at identification time); DID-20, DID-34, DID-35, DID-37, DID-38.

## DC-2 — Stage the verification coverage check by build step  (accepted, 2026-11-09)
- **Raised by:** Claude, test plan review (test plan v2)
- **Decided by:** Vaughan Lynn, 2026-11-09
- **Change:** `tools/check_verification.py` requires a test for a non-deferred T requirement only once its build step has merged. `docs/verification.md` gains a Step column (from `docs/test-plan.md` §10; D, I and A-only rows take their step from `bench/checklists.md`). For step 8 requirements (SC-1, SC-4, SC-9, SC-10, SC-11, STS-20, HW-1, HW-3, HW-6, HW-7, HW-8, PLT-2, PLT-3, PLT-8), a `bench/` procedure ID in the Test-or-procedure column satisfies the check. Before a release tag, every T row needs a passing test, a procedure with a result, or a recorded gap.
- **Why:** as written, the check failed on the first pull request, when almost nothing has tests, and could never pass for requirements verified only by a bench procedure.
- **Affects:** CI; `tools/check_verification.py`; `docs/verification.md`.
- **Docs updated in the same change:** `docs/verification.md` (intro and Step column), `docs/handoff.md` (Testing: Naming line), `CLAUDE.md` (rule 3), `docs/test-plan.md` §10.
- **Tests:** tests of `check_verification.py`: a T requirement of an unmerged step passes; one of a merged step with no test fails; a step 8 requirement with a `bench/` ID passes; release mode fails on an empty row.

## DC-1 — Python version floor until the Beacon check  (accepted, 2026-11-09)
- **Raised by:** Claude, documentation review
- **Decided by:** Vaughan Lynn, 2026-11-09
- **Change:** CI and `pyproject.toml` target Python 3.9 as the minimum until build step 2a reads the Beacon's version (PLT-6). Code avoids language features newer than 3.9. `types.py` (and any module using `X | None` annotations) starts with `from __future__ import annotations`; `X | None` is never used in anything evaluated at run time (`isinstance`, casts), where `Optional[X]` is used instead. Accepted ahead of the Nov 10 baseline; it applies from the baseline.
- **Why:** step 1 needs a version now; the Beacon's version is an open check.
- **Affects:** PLT-6; CI; `pyproject.toml`.
- **Docs updated in the same change:** this log; `docs/handoff.md` (CI line, open checks); `docs/requirements.md` (open item); `docs/modules.md` (shared types). Step 2a raises or confirms the floor with a new entry.
- **Tests:** CI runs on 3.9.

## DC-0 — Baseline at the Nov 10, 2026 cut-over  (accepted, 2026-11-10)
- **Raised by:** Vaughan Lynn
- **Decided by:** Vaughan Lynn, 2026-11-10
- **Change:** none; this marks the starting point. Decisions before this date are in the hand-off decision log (X1 to X42).
- **Why:** development starts; the repo's `docs/` becomes the only copy of the specs (X19).
- **Affects:** all module contracts start at v1.
- **Docs updated in the same change:** `docs/design-changes.md` and `docs/modules.md` added; `CLAUDE.md` rule 16.
- **Tests:** none.
