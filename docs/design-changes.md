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
