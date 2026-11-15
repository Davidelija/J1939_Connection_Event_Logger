# Saved failing examples (SC-12a)

Every JSON file here is replayed through the decode properties in
`tests/malformed/test_decode_malformed.py` on every CI run
(`test_SC_12a_saved_regressions_replay`), so a bug found once stays fixed.

**When the nightly job fails** (`.github/workflows/nightly.yml`, with a random Hypothesis
seed shown in the job summary):

1. Reproduce it locally with the seed from the summary:
   `python -m pytest tests/malformed --hypothesis-seed=<seed>`, or with the
   `@reproduce_failure` blob Hypothesis prints.
2. Save the falsifying example here as `<yyyy-mm-dd>_<short-name>.json` (format below).
3. Fix the code in the same pull request. The file stays, so CI replays the case.

**Format:**

```json
{
  "finding": "what went wrong, one line",
  "found": "2026-11-14, nightly seed 123456",
  "target": "decode",
  "batches": [
    [{"t": 0.0, "can_id": "0x1CC800F9", "data": "14b80b0000ecfe00"}]
  ]
}
```

Each frame has `t` (seconds from the start), `can_id` (hex, 29-bit) and `data` (hex),
and optionally `extended` (default true), `remote` and `error` (default false).
`target` is `decode` for now; a new target needs its replay in the test module first.
