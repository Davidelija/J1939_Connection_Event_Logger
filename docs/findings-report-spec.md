# Findings (validation) report: specification and test-script brief

**Decision F10 / X30 (Vaughan, Nov 7, 2026):** adopt a findings report as a deliverable. It is written in build step 9 and produced at every cut-line tier (X13), even if it only reports vcan results. The test scripts that produce its data are developed in a separate chat; this brief is the starting point for that chat.

## 1. Purpose

The test report and verification matrix show the logger **meets its requirements** (verification). The findings report answers the question the outside party (ORNL) cares about: **can a logger at the 9-pin diagnostic port detect and identify connected devices from their messages, and how well?** That is the V-model's **validation** step.

- **Deliverable:** `docs/findings.md`, about 2 pages, with the data in `docs/findings-data/`.
- **Audience:** the recipient (ORNL), the instructor, and whoever continues the work.

## 2. Report outline

1. **Setup:**
   - the bench and vehicle traffic used (rig captures, the minimum acceptance setup, or a truck)
   - the cut-line tier reached
   - software, config and device library versions
   - the list of devices tested (make, model, software version, and whether each was used to build the library)
2. **Detection:**
   - connections detected out of connections made
   - time from a device's first frame to its `connection_start` record (DET-16): median and maximum, against the 2 s limit
   - results broken down by device and by scenario
3. **Identification:**
   - accuracy of category and type against the ground truth
   - make accuracy, if a manufacturer list was loaded
   - a confusion table (what was mistaken for what)
   - how much each evidence source contributed: NAME, request pattern, self-reported identity
   - confidence calibration: how often "high" was correct
4. **False alarms:**
   - high and notice events over the SC-10 24-hour soak, with no device connected
   - events per hour, and each false alarm explained
5. **Misses and misclassifications:**
   - every missed or wrong result, with its cause
   - the result of the DET-13 request-rule check from build step 5 (decision X15)
6. **Limits and recommendations:**
   - what message-based detection can't do (listen-only devices, spoofed NAMEs, clones, and a copied NAME of a known device absent that session, recorded as a move)
   - what to try next (for example the out-of-scope timing and cadence methods)
   - what a fleet deployment would need

**Rule:** every number in the report is produced by a script from logged data, never typed in by hand. The report states which script and which data produced each table.

## 3. Ground truth: scenario manifest

Scoring needs to know what really happened in each run. Each scenario (the SC-11 suite and any truck or device runs) gets a manifest file, written before the run, listing what was connected and when.

Suggested format, `findings-data/scenarios/<scenario-id>.json`:

```json
{
  "scenario": "sc11-07-code-reader",
  "tier": "vcan | bench | truck",
  "traffic": "tests/fixtures/rig/rig-idle-01.log",
  "logger": {"sw": "0.4.0", "config": "cfg-v3", "inventory": "inv-v2", "library": "lib-v1"},
  "events": [
    {
      "device": "code reader A",
      "make": "…", "model": "…", "sw_version": "…",
      "expected_category": "external device (unrecognized)",
      "expected_type": "diagnostic tool, code reader",
      "in_library": true,
      "connect_utc": "2026-11-20T15:02:10.000Z",
      "disconnect_utc": "2026-11-20T15:09:40.000Z",
      "expected_flags": ["control_flag:65235"]
    }
  ]
}
```

For replayed fixtures, connection times can be computed from the fixture rather than entered by hand.

## 4. Scripts needed (for the test-script chat)

Put the scripts in `tools/findings/`. Each reads session files, raw captures and manifests, and writes a CSV and a short Markdown table to `docs/findings-data/`. All scripts are pure Python with the standard library, and each has its own unit tests.

| Script | Input | Output | Metric |
|---|---|---|---|
| `match_events.py` | Session files plus manifests | One row per expected event, matched to the logger's `connection_start`/`connection_end` (by time window and SA/NAME); unmatched rows on either side | Basis for every other script |
| `detection.py` | Output of `match_events` | Detected/missed per device and scenario; latency from first frame (from the raw capture or fixture) to `connection_start` `utc` and `written` | Detection rate; DET-16 latency (median, max, % under 2 s) |
| `identification.py` | Output of `match_events` plus `identification` records | Confusion table (expected vs logged category and type); accuracy by evidence source; confidence calibration | Identification accuracy |
| `false_alarms.py` | Soak session files (SC-10) plus their manifest (no devices expected) | Every high or notice event not in the manifest, per hour | False alarm rate |
| `flags.py` | Output of `match_events` plus `control_flag` and DM activity | Expected vs logged control flags, DM activity and memory transfers (ETP, decision X28) | Flag accuracy |
| `det13_check.py` | Rig captures | For each vehicle ECU, whether it sends Requests other than Request for Address Claim, and what DET-13 would call it if it woke late | Decision X15 input (build step 5) |
| `build_report.py` | All of the above | The tables for `docs/findings.md`, with script and data versions noted | Report assembly |

**Checks the scripts should make** (fail loudly, not silently):
- every session file's hash chain verifies (call `verify_chain`) before it is scored
- the logger, config, inventory and library versions match the manifest
- every `raw_capture` window contains its record's `utc`
- no manifest event is matched twice

## 5. Data the build must keep for this

- Rig captures with VINs anonymized (`tests/fixtures/rig/`).
- Session files, raw captures and the diagnostic log from every SC-11 and SC-10 run, kept rather than deleted after the tests pass (decision X33).
- A device sheet for each characterized ELD and tool: make, model, software version, and where it came from (team-owned or borrowed).
- The device library version used for each run.

## 6. By cut-line tier (decision X13)

| Tier reached | What the report can say |
|---|---|
| 1: functional core on vcan | Detection and identification on replayed fixtures and rig captures only; clearly labelled as replay, not live devices |
| 2: A1–A4 on the Beacon | Adds live detection timing on hardware and the SC-9 load figures |
| 3: A5–A8, SC-10, SC-11 | Full results: live devices, the 24-hour false-alarm rate, identification accuracy on characterized devices |

## 7. Open points for the test-script chat

- **Devices: use what the team has** (decision X32). The report names every device tested, states which ones built the library and which only tested it, and states the limitation this puts on the identification results.
- **How connection times are recorded for live bench runs:** a manual log, a scripted stand-in on Beacon 2, or a marker frame.
- **Keeping test and characterization devices separate:** whether devices used to build the library are tested separately from devices not in it, so the accuracy isn't inflated.
