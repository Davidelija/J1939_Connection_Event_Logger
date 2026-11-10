<!-- Title: [step N | module] short description, e.g. "[step 1 | decode] TP reassembly" -->

## What this changes
<one or two sentences; requirement IDs>

## Definition of done
- [ ] Tests pass in CI, including ruff, mypy, the malformed-input tests and `demo/run_demo.sh` (from step 2)
- [ ] Every new test name starts with the requirement ID it verifies
- [ ] Anything that departs from a requirement, contract, log format or error table has an **accepted** entry in `docs/design-changes.md`, and the affected specs are updated in this pull request (contract version raised in `docs/modules.md`)
- [ ] `docs/verification.md` rows updated (test or procedure, where, result, date, evidence)
- [ ] `docs/errors.md` rows added or updated, with their Test column filled in
- [ ] User manual sections for this change updated (command reference and troubleshooting table if a command, message or fault changed)
- [ ] `CHANGELOG.md` Unreleased section updated
- [ ] A line added to `docs/reviews.md` for the human reviewer
- [ ] No licensed content added; no hardware-specific code outside `platform/`

## State (for the next session)
- **Step / module:**
- **Done:**
- **Not done:**
- **Open DC entries:**
- **Next action:**
