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
