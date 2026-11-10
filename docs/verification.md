# Verification matrix

One row per requirement in `docs/requirements.md`. Update the rows a build step touches at the end of that step (hand-off build plan); Beacon go/no-go results from step 2a are recorded here too.

- **Test or procedure:** the test name (it starts with the requirement ID) or the `bench/` procedure and step.
- **Where:** vcan, Beacon, backup platform, or not verified.
- **Result:** pass, fail, or not supported on the Beacon, with the reason.
- **Evidence:** the CI run, test report section or results file.

The goal is a Beacon result for every hardware-relevant T requirement. If a Beacon check fails or time runs out, the vcan build is handed over and each gap is recorded here (Where: not verified, or Result: not supported on the Beacon, with the reason) and summarized in `docs/transition.md` §2 (decisions X9, X12).

A CI check fails if a requirement marked T has no test, skipping rows whose status is Deferred.

| ID | Method | Test or procedure | Where | Result | Date | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| SC-1 | I, T |  |  |  |  |  |
| SC-2 | T |  |  |  |  |  |
| SC-3 | T |  |  |  |  |  |
| SC-4 | T |  |  |  |  |  |
| SC-5 | D |  |  |  |  |  |
| SC-6 | I, A |  |  |  |  |  |
| SC-8 | D |  |  |  |  |  |
| SC-9 | T |  |  |  |  |  |
| SC-10 | T |  |  |  |  |  |
| SC-11 | T |  |  |  |  |  |
| SC-12 | T | Deferred, not built |  |  |  |  |
| SC-12a | T |  |  |  |  |  |
| NP-1 | T |  |  |  |  |  |
| NP-2 | T |  |  |  |  |  |
| NP-3 | T |  |  |  |  |  |
| NP-4 | T |  |  |  |  |  |
| NP-5 | I, T |  |  |  |  |  |
| NP-6 | T |  |  |  |  |  |
| NP-7 | T |  |  |  |  |  |
| NP-8 | T |  |  |  |  |  |
| NP-9 | T |  |  |  |  |  |
| NP-11 | T |  |  |  |  |  |
| NP-12 | T |  |  |  |  |  |
| NP-13 | T |  |  |  |  |  |
| NP-14 | T |  |  |  |  |  |
| NP-15 | T |  |  |  |  |  |
| NP-16 | T |  |  |  |  |  |
| NP-17 | T |  |  |  |  |  |
| NP-18 | T |  |  |  |  |  |
| NP-19 | T |  |  |  |  |  |
| TRN-2 | D |  |  |  |  |  |
| TRN-3 | T |  |  |  |  |  |
| TRN-4 | D |  |  |  |  |  |
| TRN-5 | D |  |  |  |  |  |
| TRN-6 | I |  |  |  |  |  |
| TRN-7 | I |  |  |  |  |  |
| TRN-9 | T |  |  |  |  |  |
| TRN-10 | T |  |  |  |  |  |
| TRN-11 | T |  |  |  |  |  |
| TRN-12 | T |  |  |  |  |  |
| TRN-13 | I |  |  |  |  |  |
| TRN-14 | T |  |  |  |  |  |
| TRN-15 | T |  |  |  |  |  |
| DET-1 | T |  |  |  |  |  |
| DET-2 | T |  |  |  |  |  |
| DET-3 | T |  |  |  |  |  |
| DET-4 | T |  |  |  |  |  |
| DET-5 | T |  |  |  |  |  |
| DET-6 | T |  |  |  |  |  |
| DET-7 | T |  |  |  |  |  |
| DET-8 | T |  |  |  |  |  |
| DET-9 | T |  |  |  |  |  |
| DET-10 | T |  |  |  |  |  |
| DET-11 | T |  |  |  |  |  |
| DET-12 | T |  |  |  |  |  |
| DET-13 | T, A |  |  |  |  |  |
| DET-14 | T |  |  |  |  |  |
| DET-15 | T |  |  |  |  |  |
| DET-16 | T |  |  |  |  |  |
| DET-17 | T |  |  |  |  |  |
| DET-18 | T |  |  |  |  |  |
| DET-19 | T |  |  |  |  |  |
| IDN-1 | T |  |  |  |  |  |
| IDN-2 | I |  |  |  |  |  |
| IDN-3 | T, A |  |  |  |  |  |
| IDN-4 | A |  |  |  |  |  |
| IDN-5 | D |  |  |  |  |  |
| IDN-6 | T |  |  |  |  |  |
| IDN-7 | T | Deferred, not built |  |  |  |  |
| LOG-1 | I |  |  |  |  |  |
| LOG-2 | T |  |  |  |  |  |
| LOG-3 | I, T |  |  |  |  |  |
| LOG-4 | I |  |  |  |  |  |
| LOG-5 | T |  |  |  |  |  |
| LOG-6 | I |  |  |  |  |  |
| LOG-7 | T |  |  |  |  |  |
| LOG-8 | I |  |  |  |  |  |
| LOG-9 | T |  |  |  |  |  |
| LOG-10 | T |  |  |  |  |  |
| LOG-11 | T |  |  |  |  |  |
| LOG-12 | T |  |  |  |  |  |
| LOG-13 | I |  |  |  |  |  |
| LOG-14 | T |  |  |  |  |  |
| LOG-15 | T |  |  |  |  |  |
| LOG-16 | T |  |  |  |  |  |
| LOG-17 | T |  |  |  |  |  |
| LOG-18 | T |  |  |  |  |  |
| LOG-19 | T, I |  |  |  |  |  |
| LOG-20 | T |  |  |  |  |  |
| LOG-21 | T | Deferred, not built |  |  |  |  |
| LOG-22 | T |  |  |  |  |  |
| LOG-23 | T |  |  |  |  |  |
| LOG-24 | T | Deferred, not built |  |  |  |  |
| STS-1 | D |  |  |  |  |  |
| STS-2 | D |  |  |  |  |  |
| STS-3 | I |  |  |  |  |  |
| STS-4 | I, D |  |  |  |  |  |
| STS-5 | D |  |  |  |  |  |
| STS-7 | D |  |  |  |  |  |
| STS-8 | I |  |  |  |  |  |
| STS-9 | T |  |  |  |  |  |
| STS-10 | T | Deferred, not built |  |  |  |  |
| STS-11 | T |  |  |  |  |  |
| STS-12 | T |  |  |  |  |  |
| STS-13 | T | Deferred, not built |  |  |  |  |
| STS-14 | T | Deferred, not built |  |  |  |  |
| STS-15 | T | Deferred, not built |  |  |  |  |
| STS-16 | T | Deferred, not built |  |  |  |  |
| STS-17 | T |  |  |  |  |  |
| STS-18 | T |  |  |  |  |  |
| STS-19 | T |  |  |  |  |  |
| STS-20 | T |  |  |  |  |  |
| STS-21 | T | Deferred, not built |  |  |  |  |
| STS-22 | T | Deferred, not built |  |  |  |  |
| STS-23 | T |  |  |  |  |  |
| LAP-1 | D |  |  |  |  |  |
| LAP-2 | D |  |  |  |  |  |
| LAP-3 | D |  |  |  |  |  |
| LAP-4 | T |  |  |  |  |  |
| LAP-5 | T |  |  |  |  |  |
| LAP-6 | T |  |  |  |  |  |
| LAP-8 | T |  |  |  |  |  |
| LAP-9 | T |  |  |  |  |  |
| LAP-10 | D |  |  |  |  |  |
| LAP-11 | T |  |  |  |  |  |
| LAP-12 | D |  |  |  |  |  |
| LAP-13 | D |  |  |  |  |  |
| LAP-14 | D |  |  |  |  |  |
| LAP-15 | D |  |  |  |  |  |
| LAP-16 | T | Deferred, not built |  |  |  |  |
| LAP-17 | D |  |  |  |  |  |
| HW-1 | I, T |  |  |  |  |  |
| HW-2 | I |  |  |  |  |  |
| HW-3 | T |  |  |  |  |  |
| HW-4 | I |  |  |  |  |  |
| HW-5 | T | Deferred, not built |  |  |  |  |
| HW-6 | T |  |  |  |  |  |
| HW-7 | T |  |  |  |  |  |
| HW-8 | T |  |  |  |  |  |
| HW-9 | I |  |  |  |  |  |
| HW-10 | I |  |  |  |  |  |
| PLT-1 | I |  |  |  |  |  |
| PLT-2 | T |  |  |  |  |  |
| PLT-3 | I, T |  |  |  |  |  |
| PLT-4 | T | Deferred, not built |  |  |  |  |
| PLT-5 | I |  |  |  |  |  |
| PLT-6 | I, D |  |  |  |  |  |
| PLT-7 | A |  |  |  |  |  |
| PLT-8 | I, T |  |  |  |  |  |
