# J1939 event logger: user manual

Skeleton. Each section is filled in by the build step that delivers its feature (hand-off, Documentation to deliver) and finished in step 9 with real bench output. Each task gives when to do it, the steps, example screen output and what can go wrong.

## 1. Getting started

### What the logger does

The logger sits on a short tap at a heavy truck's 9-pin J1939 diagnostic connector. During training it learns which devices normally sit on the vehicle network. After that it watches every session, from key-on to key-off, for anything new: an ELD, a scan tool or any other device.

**What it records.** For each new device: when it connected and disconnected, its address and NAME, what kind of device it seems to be, what it sent and what it asked for. It also records raw CAN frames from 10 s before to 60 s after each new connection. Records are hash-chained, so a changed or missing record shows up when the logs are checked.

**What it sends.** Only a small, fixed set of frames: its own address claim (always at an address from 128 to 247, and it always gives way in a conflict), and requests for address claims, the vehicle's time and date, the VIN, and the identity of new devices, plus the replies J1939 requires of every node (answering a request for its address claim, refusing other requests addressed to it, and transport-protocol handshakes for replies sent to it). It sends at most 10 frames a second.

**What it never does.** It never sends a command, a clear or a write, and never gives data to other devices. It does not use Wi-Fi or Bluetooth. It never deletes its event logs, not even after retrieval.

**Where the data goes.** Everything is written to the logger's card. A maintenance laptop retrieves the logs over a wired SSH connection, checks the chain and produces a report for review.

*(The rest of this chapter is written as each build step lands.)*

- What you need *(step 7)*
- What you need *(step 7)*
- Running the no-hardware demo on a Linux machine or VM (`demo/run_demo.sh`) *(from step 2)*
- Setting up the Windows laptop and connecting it: the logger's fixed address (`network.address`) and its DHCP server on the wired port *(step 7)*
- Installing the logger, including the VIN request address `requests.vin_sa` (default 0, the engine) *(step 8)*

## 2. Everyday use
- The status light and the `status` screen *(steps 7, 8)*
- Training a truck; PTO is detected from Power Takeoff Information 1 (PGN 65264, engaged when Power Takeoff Speed is above zero) or declared by the operator *(step 6)*
- Reviewing new events *(step 7)*
- Changing the inventory *(step 6)*
- Retrieving logs and running the report *(step 7)*
- Reading the report *(step 7)*
- Changing a setting *(step 7)*

## 3. Less common tasks
- Restart or retrain *(step 7)*
- Moving the logger to another truck by hand *(step 8)*
- Replacing the card or removing the logger; the card is ext4, so card-swap retrieval needs a Linux machine or VM; the new card starts a new chain, which the chain check reports as a declared break; session numbers carry on from the logger's internal flash (if that isn't writable, `install.sh` asks for the next session number) *(step 8)*

## 4. For analysts
- The files on the card and the session file layout *(step 2)*
- The chain check and what to do if it fails *(step 2)*
- Opening raw captures *(step 6)*

## 5. Admin
- Logging in, file locations, starting and stopping the service, the diagnostic log *(step 8)*
- Installing, updating and rolling back from the release bundle *(steps 8, 9)*
- Adding and removing operator keys *(step 7)*
- Updating the device library: characterize the device on the bench, add an entry to `data/device_library.json` (function codes, typical and never-used PGNs, optional make and model), raise the library version, install it with the release, then rerun the identification tests and record the new library version in the findings report's setup section. The repo source `data/device_library.json` is installed on the logger as `library/lib-vN.json`; raising the library version means changing the `library` field (`lib-v1` → `lib-v2`); the format stays `lib-1`. *(step 5)*
- The hardening checklist and the Beacon procedure *(step 8)*
- Deleting data by hand *(step 8)*

## 6. Reference
- Troubleshooting table, generated from `docs/errors.md` *(each step adds its rows)*
- Command reference *(step 7)*
- Glossary, FAQ, escalation contact *(step 9)*

## Appendix: quick card *(step 9)*
