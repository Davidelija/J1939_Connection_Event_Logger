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
| 2. Sessions and chain |  |  |  |  |
| 2a. Beacon go/no-go |  |  |  |  |
| 3. Transmit |  |  |  |  |
| 4. Detection |  |  |  |  |
| 5. Identification |  |  |  |  |
| 6. Training and inventory |  |  |  |  |
| 7. Laptop tool |  |  |  |  |
| 8. Beacon |  |  |  |  |
| 9. Documentation |  |  |  |  |
