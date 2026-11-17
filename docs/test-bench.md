# Test bench

What the hardware test bench is, how it is wired and what runs on it. It brings together what `docs/background/beacon-application.md` (Roles of the two Beacons), `docs/porting.md` §5 (minimum acceptance setup), `docs/test-plan.md` and `docs/handoff.md` say about the bench, so a newcomer can set it up from one page. Where those documents and this one differ, they win; report the difference.

The bench is used for:

- **Build step 2a**, the Beacon go/no-go (`docs/step-2a-procedure.md`).
- **Build step 8**, the acceptance tests A1 to A8, the SC-9 load test, the SC-10 24-hour soak, the SC-11 scenario suite and the B-procedures (`bench/`, owned by the test-script writers, DC-4).
- **Validation**, the detect-and-identify scenario runs scored for the findings report (`docs/findings.md`).

Nothing that transmits is run on a truck until step 8 has passed on the bench.

## Two ways to build it

| | Full rig | Minimum acceptance setup (decision X20) |
| --- | --- | --- |
| Bus traffic | Real ECUs on the rig bus | Rig captures (`tests/fixtures/rig/`) replayed with `canplayer` from a second CAN interface |
| Good for | Everything: 2a, A1 to A8, SC-9, SC-10, SC-11, validation, building the device library | 2a, A1 to A8 and the B-procedures; not the validation runs or the device library, which need real devices |
| Extra hardware | The rig | Two SocketCAN interfaces (or one two-channel interface) and a 9-pin breakout harness |

Step 2a needs only two CAN nodes on a terminated bus, so either setup works for it.

## Equipment

| Item | What it is for | Notes |
| --- | --- | --- |
| **Beacon 1** | The logger: the unit under test | DG Beacon: embedded Linux, 1 GHz processor, six CAN / CAN FD channels with per-channel bit rate, termination and error reporting, 512 MB NAND flash, microSD up to 64 GB, USB, 100 Mb Ethernet, Wi-Fi; 6 to 32 VDC input, about 1.6 A at 12 V; rated −40 to +85 °C. SocketCAN support, listen-only mode, a real-time clock and controllable LEDs are **unconfirmed until step 2a** |
| **Beacon 2** | The test instrument, bench only: the **witness** (records everything on the bus, independently of the logger) and the **device stand-in** (sends address claims, requests and DM reads like an ELD or code reader, contests the logger's address, sends flagged control PGNs) | Same model. Any SocketCAN node with can-utils can stand in for it in step 2a |
| **Rig bus** | The J1939 network | Twisted pair, **terminated with 120 Ω at both ends**, at 250 kbit/s (and 500 kbit/s for the A1 and A5 checks). Measure about 60 Ω between CAN-H and CAN-L with the power off |
| **Rig ECUs** (full rig only) | Real baseline traffic | Whatever the rig carries; record their NAMEs and addresses in the evidence before each run |
| **Short tap** | Connects Beacon 1 the way it will connect on a truck | A 9-pin Deutsch Y-splitter with a pass-through port and a short leg to Beacon 1; target under 0.5 m of added stub including the logger cable (HW-1). **No terminator** in the tap (HW-2). Purpose-built; see `docs/background/beacon-application.md`, Hardware stack |
| **9-pin breakout harness** (minimum setup) | Gives the bus a diagnostic connector without a vehicle | Terminated at both ends |
| **Bench power supply** | Powers both Beacons in place of a truck battery | Adjustable 12 and 24 V, at least 3 A, with an output switch: step 2a power-cycles the Beacon, and A5 dips the voltage for a cranking brownout |
| **Maintenance laptop** | Runs `j1939ctl` and collects evidence | Windows with the OpenSSH client for the LAP-1 check; Ethernet port and a USB cable for the Beacon's USB-B port |
| **Linux machine or VM** | can-utils, reading ext4 cards, building the release bundle | Needed for card-swap retrieval (the card is ext4) and for preparing the step 2a wheels |
| **microSD cards** | The logger's storage | Industrial grade, rated for continuous writes, formatted ext4 (PLT-5); 64 GB to start (HW-9). Keep a spare for the card-swap tests |
| **USB stick** | Carries the release wheels for the offline install check (step 2a B3, B4) | Any |
| **Known-good ELDs and diagnostic tools** (full rig) | Plugged into the tap's pass-through port to build the device library and run the SC-11 scenarios | Record make, model and firmware for each |
| **Status light** (only if the Beacon's LEDs are not controllable) | STS-1 | A USB indicator; decided in step 2a (E1) |
| **RTC module** (only if the Beacon has no real-time clock) | HW-7, PLT-3 | USB or I2C; decided in step 2a (C1 to C3) |

## Wiring

```
                 120 Ω                                                   120 Ω
   bus end  ──[term]──┬────────────── rig bus (CAN-H / CAN-L) ─────────┬──[term]──  bus end
                      │                         │                       │
                 rig ECUs                9-pin diagnostic          Beacon 2, channel 0
              (full rig only)               connector              (witness / stand-in,
                                                │                   termination OFF)
                                          short tap (Y)
                                         ╱             ╲
                              pass-through port     short leg (< 0.5 m)
                              (ELD / scan tool)          │
                                                   Beacon 1, channel 0
                                                   (logger, termination OFF)

   Bench supply ── Beacon 1 power, Beacon 2 power, and the bus ground (pin A)
   Laptop ── Ethernet or USB-B ── Beacon 1 (SSH, j1939ctl)
```

Rules:

- **Exactly two terminators,** at the two ends of the bus. Neither Beacon terminates: set `termination 0` on their channels where the controller supports it, and check that the tap has none. Each extra 120 Ω terminator lowers the bus resistance (60 Ω correct; 40 Ω with one extra, 30 Ω with both Beacons terminating) and distorts the signal.
- **One shared ground.** The supply's negative goes to pin A of the diagnostic connector and to both Beacons.
- **Short stubs.** Keep Beacon 2's stub short too; it is a node on the same bus.
- **Same bit rate everywhere.** The rig runs at 250 kbit/s unless a test says 500 kbit/s; set both Beacons to match.
- **Wi-Fi and Bluetooth off** on Beacon 1 (STS-20); the laptop connects by cable only.

## Software on the bench

| Where | What |
| --- | --- |
| Both Beacons | can-utils (`candump`, `cansend`, `cangen`, `canplayer`), `ip` (iproute2), systemd. Root access on both |
| Beacon 1 (from step 8) | The release bundle, installed by `install.sh` |
| Beacon 2 | The device stand-in and address-claim contender (`ecu_sim` in `bench/tools/`, test-script writers) |
| Laptop | `j1939ctl`, the repository, Python 3.9 or later |
| Linux machine | can-utils, Python, `pip` (to build wheels for the Beacon's architecture) |

## Safety

- Transmit tests (claims, requests, contests, flagged control PGNs) run **on the bench only**. Never on a vehicle before step 8 passes.
- Shorting CAN-H to CAN-L (to force errors in step 2a A6 and A7) is done **on the rig only**, briefly, with no vehicle connected.
- Power-cycle with the supply's output switch, not by pulling connectors live.

## Evidence and records

- Command output and photos go in `docs/test-evidence/`, named `<ID>_<date>.<ext>` (for example `PLT-1_2026-11-20.txt`).
- Inspection, demonstration and analysis items are signed in `bench/checklists.md`; one observer is enough (DC-28).
- Results go in `docs/verification.md` (Where: Beacon or backup platform; Result; Date; Evidence) and, for the Beacon open checks, in "Open items affecting requirements" in `docs/requirements.md`.
- Before each run, write down: the date, the people, both Beacons' serial numbers and software versions, the rig's ECUs, the supply voltage and the bit rate.

## Still open about the bench

These are answered by step 2a and recorded there: whether the Beacon's channels appear as SocketCAN interfaces, whether listen-only works, whether the controller can switch termination off, whether there is a real-time clock, whether an LED is controllable, where the card mounts and whether internal flash is writable. The tap cable's total stub length, including the vehicle's own connector stub, is an open item for HW-1.
