# J1939 event logger: user manual

Skeleton. Each section is filled in by the build step that delivers its feature (hand-off, Documentation to deliver) and finished in step 9 with real bench output. Each task gives when to do it, the steps, example screen output and what can go wrong.

## 1. Getting started
- What the logger does (what it records, what it sends, what it never does, where the data goes) *(step 1)*
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
