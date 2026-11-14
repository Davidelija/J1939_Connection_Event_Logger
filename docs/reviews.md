# Review record

One line per build step, completed by a team member who reviewed the code Claude Code wrote.

| Step | Date | Reviewer | What was checked | Issues found and how resolved |
| --- | --- | --- | --- | --- |
| 1. Thin slice, PR 1 (interfaces) |  |  | To check: `types.py` against `docs/modules.md` §1; the `Platform` Protocol against §4 and `docs/porting.md` §3; `FakeClock` and the `DesktopPlatform` fault plan; `fault(op)` (DC-5) and the DC-6 clarifications; CI, pinned tools and `tools/check_verification.py` |  |
| 1. Thin slice, freeze |  |  | To check: the contracts marked "frozen for step 1" in `docs/modules.md` (§1, platform, clock, capture, decode, eventlog) and the gaps listed in the freeze pull request |  |
| 1. Thin slice, PR 2 (logic) |  |  | To check: `decode` (transport reassembly, limits, Abort requests), `clock`, `capture` (timestamps, ring, errors), `eventlog` append and hash, minimal `detect`, `session` and `main` (DC-9); the vcan0 gate test |  |
| 1. Thin slice |  |  |  |  |
| 2. Sessions and chain, freeze |  |  | To check: the contracts marked "frozen for step 2" in `docs/modules.md` and the gaps listed in the freeze pull request; `docs/module-map.md` |  |
| 2. Sessions and chain, PR 1 |  |  | To check: `config` (safety-critical: allow-list rule, `RELEASE_*_ALLOW`), `store` (atomic writes, never overwriting versions, frees raw captures only), `clock` v2, the diagnostic log |  |
| 2. Sessions and chain, PR 2 |  |  | To check: `eventlog` (safety-critical: hashing unchanged; sync thread, parts, `scan_tail`), `session` (numbering, previous end, key-off, roll-over), DC-11 |  |
| 2. Sessions and chain, PR 3 |  |  | To check: `tools/verify_chain.py` against `docs/log-format.md` (hash rule, declared breaks, truncated lines), `demo/run_demo.sh` in CI, the user manual's demo and analyst sections; step 2 marked merged |  |
| 2. Sessions and chain |  |  |  |  |
| 2a. Beacon go/no-go |  |  |  |  |
| 3. Transmit, freeze |  |  | To check: the contracts marked "frozen for step 3" (safety-critical: `transmit`) and the gaps listed in the freeze pull request |  |
| 3. Transmit, PR 1 | 2026-11-14 | Vaughan Lynn | Reviewed before merge (reported in the Claude Code session): `transmit.py` guard and limits against NP-9, NP-16, NP-18 and DC-12; the release allow-lists moved into `transmit`; `capture` send handle; `decode` CTS/EOMA |  |
| 3. Transmit, PR 2 |  |  | To check: `address` (address choice, concede, Cannot Claim, answers and NACKs) and `requests` (sweep, Time/Date, VIN, identity, timeouts, no repeats) against NP-4 to NP-14 and LOG-9 |  |
| 3. Transmit, PR 3 | 2026-11-14 | Vaughan Lynn | Reviewed before merge (reported in the Claude Code session): `session` bit-rate gate, restart guard, bus-state disable, claim and request wiring; the witness tests; step 3 marked merged |  |
| 3. Transmit |  |  |  |  |
| 6. Training and inventory, freeze |  |  | To check: `inventory`, `rawcap` and `retention` marked "frozen for step 6"; DC-20 items 1 to 10; the two new config keys; the retention contract now follows LOG-11 |  |
| 5. Identification, PR 2 |  |  | To check: `session` loads the library and runs `identify` (when, with which PGNs), reclassification and `final_identification`, the final severity on `connection_end`; DC-19; example rec 6 and its chain; step 5 marked merged |  |
| 5. Identification, PR 1 |  |  | To check: `identify` against DET-13, DET-18, IDN-3, IDN-4, IDN-6, DC-17 and DC-18 (confidence, make precedence, ties, reclassification); the Classification rule note in `docs/requirements.md` |  |
| 5. Identification, freeze |  |  | To check: `identify` marked "frozen for step 5"; DC-17 items 1 to 10; the new `identification` fields in `docs/log-format.md` |  |
| 4. Detection, freeze |  |  | To check: the contracts marked "frozen for step 4" and the gaps listed in the freeze pull request |  |
| 4. Detection, PR 1 |  |  | To check: `monitor` against DET-7 to DET-12, DC-13 and DC-14 (control-flag `via`, known-device new PGNs, ETP tracking, bounds); the session 142 example chain recomputed for rec 8 |  |
| 4. Detection, PR 2 |  |  | To check: `detect` against DET-1 to DET-6, DET-15 to DET-17 and DC-13 (first-sweep wait, DET-3 replies, moves and same-NAME conflicts, silence versus key-off); `session` and `main` now pass `config.Inventory` |  |
| 4. Detection, PR 3 |  |  | To check: `session` drives `detect` and `monitor` (sweep signals, no-sweep conditions, `connection_end` before `session_end`, end reasons at stop and roll-over); DC-15 example fix; address claims excluded from DET-12; step 4 marked merged |  |
| 4. Detection, gaps |  |  | To check: DC-16, `decode` v3 marks Acknowledgments naming the logger as replies to it; `monitor` v1.1 and `detect` v1.1 interfaces named in `docs/modules.md` |  |
| 4. Detection |  |  |  |  |
| 5. Identification |  |  |  |  |
| 6. Training and inventory |  |  |  |  |
| 7. Laptop tool |  |  |  |  |
| 8. Beacon |  |  |  |  |
| 9. Documentation |  |  |  |  |
