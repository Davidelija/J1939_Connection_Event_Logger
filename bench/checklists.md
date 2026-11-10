# Demonstration, inspection and analysis checklist

Every requirement whose verification method includes D (demonstration), I (inspection) or A (analysis), excluding Deferred rows: 50 items. Requirements that are also T keep their tests (see `docs/test-plan.md`); this list covers the D, I or A part. Fill in **Observer**, **Date**, **Result** and **Evidence** when the item is done, and copy the result to `docs/verification.md`.

- **Observer:** the person who watched or inspected, not the person who ran the step (two people where possible: Vaughan Lynn, Elijah Umaru).
- **Evidence:** a file in `docs/test-evidence/` (photo, command output, screenshot, report), named `<ID>_<date>.<ext>`.
- **Auto** marks items also checked by an automated end-to-end test; the checklist item is still signed once on the rig.

| ID | Method | What to check | Step | Auto | Observer | Date | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SC-1 | I | Install checklist and A1: one CAN channel on one J1939 network at the 9-pin connector | 8 | | | | | |
| SC-5 | D | An ELD and a service tool plugged into the tap's pass-through port work normally with the logger running | 8 | | | | | |
| SC-6 | I, A | `src/` uses Linux and SocketCAN only; hardware code only in `platform/` (import-linter report); porting guide reviewed | 9 | Partly (import-linter) | | | | |
| SC-8 | D | The same build runs unchanged on desktop Linux against `vcan0` with `canplayer` (`demo/run_demo.sh`) | 2 | Yes (CI demo) | | | | |
| NP-5 | I | Logger NAME in `session_start` is arbitrary-address capable, on-highway, function 255, manufacturer code 2047 | 3 | Yes (COM-04) | | | | |
| TRN-2 | D | Training on the rig or truck records NAME, addresses and PGNs across key-on engine off, running, driving, and PTO where fitted | 6 / 8 | | | | | |
| TRN-4 | D | `train finish` shows the proposed inventory and asks to apply; a rejected inventory is not applied | 7 | Yes | | | | |
| TRN-5 | D | Approving a logged connection adds its NAME without retraining | 7 | Yes | | | | |
| TRN-6 | I | Inventory version files exist per confirmed training or approval, carry the VIN, and export as JSON and CSV | 6 | Yes (`store` round-trip) | | | | |
| TRN-7 | I | An inventory entry holds every TRN-7 field (entry ID, raw NAME and decoded fields, make, model, addresses, states, category, identity, PGNs, requests, how and when added) | 6 | | | | | |
| TRN-13 | I | Trained PGNs kept separate from later approvals (reason, date); vehicle configuration recorded | 6 | | | | | |
| DET-13 | A | Rig captures checked for vehicle ECUs that send requests; rule result and any change recorded (X15) | 5 | | | | | |
| IDN-2 | I | Library ships with an empty manufacturer list and its format documented; no licensed content in the repo | 5 | | | | | |
| IDN-3 | A | Identification results reviewed against the findings data (make and model sources, disagreements) | 9 | | | | | |
| IDN-4 | A | Scoring reviewed against the findings data (ties, profile matches, leave-one-out) | 9 | Yes (unit, DID tests) | | | | |
| IDN-5 | D | A new library entry added on the bench and installed with the release changes identification without a code change; header shows the library version | 5 / 8 | Yes (DID-24) | | | | |
| LOG-1 | I | One JSON-lines event file per session, wake to key-off | 2 | Yes | | | | |
| LOG-3 | I | Card is ext4; event files opened `O_APPEND` (`strace` excerpt) | 8 | Partly | | | | |
| LOG-4 | I | Every record has rec, type, sev, utc, veh\_time, prev, hash, written, clock\_valid, clock\_source; event IDs as session-record | 1 | Yes (manifest checks) | | | | |
| LOG-6 | I | `session_start` holds every LOG-6 field, including `new_card` and operator key fingerprints | 2 | Yes | | | | |
| LOG-8 | I | Each record type in `docs/log-format.md` appears in the test outputs, including every operator action | 7 | Yes (format golden files) | | | | |
| LOG-13 | I | One versioned config file; its version in each header | 2 | Yes | | | | |
| LOG-19 | I | Format version on `session_start` and every supporting file | 2 | Yes | | | | |
| STS-1 | D | Each light state seen on the Beacon (off, steady, slow, fast) and overlaps resolve fast > slow > steady (A8) | 8 | Yes (status table) | | | | |
| STS-2 | D | Slow blink stays on until every high event is cleared from the laptop; each clear logged with operator | 7 / 8 | Yes | | | | |
| STS-3 | I | Status file holds every STS-3 field | 7 | Yes | | | | |
| STS-4 | I, D | Wi-Fi and Bluetooth off at driver level (`rfkill`, `lsmod` output); no wireless interface up | 8 | | | | | |
| STS-5 | D | Only an SSH key on the logger can run commands; operator name in records comes from the key; DHCP gives the laptop an address | 7 / 8 | Yes (`ssh localhost`) | | | | |
| STS-7 | D | Retrieval report has five sections in order, groups repeats, and writes `events.csv` | 7 | Yes | | | | |
| STS-8 | I | Retrieval and review schedule agreed with ORNL and written down (TBD) | 9 | | | | | |
| LAP-1 | D | Manual procedure on a Windows laptop with Python 3 and Windows OpenSSH: every command runs | 8 | | | | | |
| LAP-2 | D | All 16 commands present with `--help` | 7 | Yes | | | | |
| LAP-3 | D | Stable IDs; actions by ID only; the prompt shows what changes, asks a reason, then y/N; warning lines for risky changes | 7 | Yes | | | | |
| LAP-10 | D | `status` home screen: one block, Next step line, clock difference, key fingerprints; the tool never sets the clock | 7 | Yes | | | | |
| LAP-12 | D | `report` and `inventory show` work on a retrieved folder with no logger | 7 | Yes | | | | |
| LAP-13 | D | `inventory export` writes CSV | 7 | Yes | | | | |
| LAP-14 | D | `train status` shows elapsed and remaining time, coverage, devices and PGN counts; status file matches | 6 / 7 | Yes | | | | |
| LAP-15 | D | Every refusal says why and what to do and exits non-zero; every command has `--help` | 7 | Yes | | | | |
| LAP-17 | D | Output uses plain words for events and categories, no internal codes | 7 | Yes | | | | |
| HW-1 | I | Tap built as specified; pass-through port present (B-HW1 measures the stub) | 8 | | | | | |
| HW-2 | I | No terminator on the tap; termination off on the logger's channel (`ip -details link show`) | 2a / 8 | | | | | |
| HW-4 | I | Beacon datasheet rating covers −40 to +85 °C | 2a | | | | | |
| HW-9 | I | Industrial-grade card, 64 GB, sizing note from the measured logging rate | 8 | | | | | |
| HW-10 | I | Logger mounted, labeled with light legend and do-not-unplug notice with contact (photo) | 8 | | | | | |
| PLT-1 | I | Linux with SocketCAN and can-utils on the platform (step 2a output) | 2a | | | | | |
| PLT-3 | I | RTC with backup battery present (step 2a); A7 for the T part | 2a | | | | | |
| PLT-5 | I | Card removable, industrial-grade, ext4; `install.sh` refuses another filesystem (`card_not_ext4`) | 8 | | | | | |
| PLT-6 | I, D | Python version on the platform meets the floor (DC-1); release installs with no internet | 2a / 8 | | | | | |
| PLT-7 | A | CPU and RAM sizing from the A4 figures plus 50% headroom, written in the transition overview | 8 | | | | | |
| PLT-8 | I | systemd with watchdog support and one controllable indicator (step 2a); A8 for the T part | 2a | | | | | |

## Step 2a additions

| Check | What | Requirements |
| --- | --- | --- |
| Boot clock | After a power cycle with no network, `date` matches `hwclock` before the service starts (`hctosys`) | LOG-16, PLT-3 |
| Internal flash | A writable partition with 100 MB free for `state.json` | LOG-5 |
| Python floor | Installed Python version recorded; DC entry raises or confirms the 3.9 floor | PLT-6, DC-1 |
