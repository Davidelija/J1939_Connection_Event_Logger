# Porting guide

How to move the logger to hardware other than the DG Beacon. All hardware-specific code is in `src/j1939logger/platform/` (hand-off rule 12); nothing else needs to change. The command path (STS-23) has no platform impact.

## 1. Check the hardware

The hardware must meet PLT-1 to PLT-8 in `docs/requirements.md` (Platform requirements); PLT-4 (sleep current) is future research. `docs/background/beacon-application.md` (Platform requirements on the Beacon) shows how the Beacon meets each one.

## 2. Buying guide

These are examples to evaluate against PLT-1 to PLT-8, not tested recommendations (decision X37).

- **Bench and development:**
  - A Raspberry Pi 4 with a PiCAN3 board: SocketCAN, RTC, 6 to 24 V supply. Caveats: its MCP2515 controller has little receive buffering and may drop frames at 500 kbit/s under load, and the input doesn't cover 24 V trucks.
  - Any Linux single-board computer with a USB-CAN adapter that has a mainline driver (for example PEAK PCAN-USB or Kvaser).
- **In-vehicle:** a vehicle-grade Linux telematics gateway (typically 12 to 36 V, several CAN/CAN FD channels). Ask the vendor about listen-only support, the RTC, and wake and sleep behaviour.

**Backup platform for this project** (decision X21): if the Beacon fails the build step 2a go/no-go on SocketCAN or listen-only, the team switches to a Linux single-board computer with a CAN interface that has a mainline SocketCAN driver and a battery-backed RTC, from the bench and development class above. It is bought only if needed; the logger stays on SocketCAN either way.

## 3. Implement the platform interface

Copy `platform/desktop.py` (the vcan reference) or `platform/beacon.py` and implement each function for your hardware.

| Function | What it must do | Requirements |
| --- | --- | --- |
| `open_can(listen_only)` | Open a raw CAN socket (`AF_CAN`, `CAN_RAW`) in listen-only or normal mode, with termination off, kernel receive timestamps (`SO_TIMESTAMP`), the per-socket drop count (`SO_RXQ_OVFL`), error frames and the logger's own frames delivered. `capture` sets the receive buffer size itself, and switches mode by closing the socket and opening it again (DC-6). `python-can` may be used here instead, for hardware without SocketCAN | PLT-2, NP-1, NP-2, HW-2, LOG-15 |
| `bitrate_check()` | Confirm 250 or 500 kbit/s from clean received frames while listen-only | SC-2, NP-1 |
| `set_light(pattern)` | Show steady, slow blink or fast blink on the one indicator | STS-1, PLT-8 |
| `now()` | Return monotonic time for timers and, when the real-time clock is valid, wall-clock time with source `rtc`; otherwise no wall time and source `elapsed` (time since wake). The vehicle-time offset is kept by `clock`, not here (DC-6) | LOG-16 |
| `rtc_ok()` | Report whether the real-time clock is valid | HW-7, PLT-3 |
| `on_wake()` | Report wake and ready times | HW-8 |
| `watchdog_kick()` | Notify the systemd watchdog | STS-18 |
| `paths()` | Give the card, internal flash and key locations | LOG-11, LAP-8 |
| `fault(op)` | Do nothing. On the desktop it raises the fault plan's socket and storage faults; the logger calls it before each receive, send, card write, card sync and flash write (DC-5) | LOG-22, NP-18 |

Hardening (STS-20) is an install procedure in `release/` (`install.sh` and the install checklist), not a platform function. *(Function details are fixed in build step 1 and updated here if they change.)*

## 4. Install

Format the card as ext4, build the release bundle, copy it over SSH and run `release/install.sh`, which refuses any other filesystem and raises `net.core.rmem_max` (user manual, Admin).

## 5. Minimum acceptance setup

A small bench on which A1 to A8 run without a vehicle or rig ECUs (decision X20):

- Two CAN interfaces supported by SocketCAN, or one two-channel interface. One replays the shipped rig captures (`tests/fixtures/rig/`) with `canplayer` as the vehicle; the other records as the witness.
- A 9-pin breakout harness terminated with 120 Ω at both ends.
- An adjustable bench supply able to dip for the brownout test (A5).
- The scripted address-claim contender in `bench/tools/`, for the A3 conflict case.

No current meter is needed: sleep current is future research (decision X39).

## 6. Run the acceptance tests

Run `bench/` acceptance tests A1 to A8 on the new hardware with an independent recorder as witness, and record each result in `docs/verification.md` with the hardware name.

| Test | Checks | Requirements | Minimum setup |
| --- | --- | --- | --- |
| A1 | Bit-rate detection | SC-2, NP-1 | Yes |
| A2 | Listen-only start, then normal mode | NP-1, NP-2 | Yes |
| A3 | Transmit-guard witness test, including an address-claim conflict | NP-3, NP-9, NP-16, NP-18, SC-4 | Yes |
| A4 | 60% load with bursts; CPU, memory and drops | SC-9, PLT-7 | Yes |
| A5 | Power loss and cranking brownout | HW-6, LOG-5, LOG-12, LOG-14 | Yes |
| A6 | Wake and ready time | HW-8 | Yes; better confirmed on a vehicle |
| A7 | Real-time clock across power loss | HW-7, PLT-3, LOG-16 | Yes |
| A8 | Status light and watchdog restart | STS-1, STS-18, PLT-8 | Yes |

SC-4 (no rise in bus errors) and the SC-11 scenario suite are better confirmed on a vehicle or the full rig. The port is done when A1 to A8 pass, or each failure is recorded with its effect.
