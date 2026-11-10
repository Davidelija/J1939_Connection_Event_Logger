# J1939 event logger: transition overview

Written for the recipient of the prototype. Sections marked *(at hand-over)* are completed in build step 9.

## 1. What it does and its status

The logger sits on a heavy truck's 9-pin J1939 diagnostic connector, learns the vehicle's known-good devices in a training run, and logs every new device that connects (ELDs, scan tools, anything else) in a hash-chained event log. A Windows laptop tool trains it, reviews events and retrieves logs.

Status *(at hand-over)*: a prototype, not a fleet-ready deployment. The goal is a build proven on a DG Beacon on the bench; if a Beacon check failed or time ran out, the build proven on simulated CAN (vcan) is handed over with the Beacon results achieved so far, and each gap recorded (decisions X12, X13). This section states which, the cut-line tier reached, and the software version and release tag.

## 2. What was verified and where

*(at hand-over)* A summary of `docs/verification.md`:

- the cut-line tier reached: (1) functional core on vcan; (2) acceptance tests A1 to A4 on the Beacon or backup platform; (3) A5 to A8, the SC-10 24-hour soak and the SC-11 scenario suite
- how many requirements were verified on vcan, on hardware, or not at all, and each gap with its reason
- the SC-9 CPU, memory and drop figures, and the wake and ready times (sleep is future research)
- the findings report (`docs/findings.md`): how well the logger detected and identified the devices tested

## 3. Core profile

The Demo subset in `docs/requirements.md` is the core: its functional core covers detection, evidence and the everyday laptop commands. Requirements marked Deferred are documented but not built; the rest are optional.

Out of scope for this prototype, including timing and cadence fingerprinting: see requirements, Not required.

## 4. What you must obtain

- SAE J1939 Digital Annex (codes are decoded during analysis, not in the logger).
- A manufacturer code list you are licensed to use. The release ships the list empty with its format documented.
- The J1939 standards cited in the requirements (SAE J1939-13, -14, -15, -21, -71, -73 and -81).
- Hardware that meets PLT-1 to PLT-8 (requirements, Platform requirements), or a DG Beacon. The buying guide in `docs/porting.md` gives examples to evaluate.
- The minimum acceptance setup in `docs/porting.md`, to run acceptance tests A1 to A8 without a vehicle.
- A Linux machine or VM for the no-hardware demo; a Windows laptop with Python 3 and OpenSSH for the operator tool.
- DG Beacon software, only if you use a Beacon.

## 5. Getting started

1. Run the no-hardware demo, `demo/run_demo.sh`, on a Linux machine or VM (WSL2's default kernel lacks the `vcan` module, as far as known).
2. Using the logger: `docs/user-manual.md`.
3. Moving it to other hardware: `docs/porting.md`, then acceptance tests A1 to A8.
4. Building and testing on a desktop: `README.md`.

## 6. Known limits

From the requirements (Known limitations), quoted as written there, including:

- "Logs on a removed microSD card are readable and not encrypted. They are hash-chained but not signed (LOG-24 deferred), so someone holding the card could rewrite records not yet retrieved and recompute the chain; the last hash kept on the laptop at each retrieval shows tampering with anything already retrieved."
- "Operators have a shell on the logger (STS-21 deferred); their tool actions are logged, but direct file edits are not."

*(at hand-over: any limits found on the bench)*

## 7. Decisions left to you

- Retrieval schedule and reviewer (STS-8).
- Escalation contact for a suspicious device.
- Data handling and retention for retrieved logs (they contain VINs and device IDs).

## 8. Licence and support

The code is provided under the MIT License (`LICENSE`), without warranty. No support continues after the semester. The user manual, its troubleshooting table and the decision log in `docs/handoff.md` are the only references.
