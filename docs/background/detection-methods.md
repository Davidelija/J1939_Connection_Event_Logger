# Detecting External Devices on a J1939 Network: Methods and Challenges

Nov 2, 2026 · @Vaughan

> **Background as of Nov 7, 2026.** Where this document differs from `docs/requirements.md`, the requirements win (for example, a known NAME at a new, uncontested address is an `address_change`, not a conflict: DET-4).

## Purpose and scope

A logger that listens to the bus and sends a small set of identification requests can detect most external devices that transmit, and devices that only listen are out of scope. This doc lists the known detection methods for the diagnostic-port connected-devices logger and the challenge that limits each one.

- **External device** means anything connected through the diagnostic port that is not part of the vehicle's own network: ELDs, scan tools and RP1210 adapters, telematics units and aftermarket add-ons.

- **Non-disruptive constraint:** the logger may claim an address and send a small, fixed set of identification requests. It must not disturb normal vehicle network operation, trigger actions in any ECU, or compete for addresses already in use.

- **Two jobs:** *detection* (something new is connected, and when) and *identification* (what it is: make, model, type). Each method below notes which job it serves.

- Sections 2 to 4 go from message content, to timing, to signals below the message level. Section 5 maps them to ELDs and diagnostic tools, and section 6 covers challenges common to all methods.

**Protocols:** J1939 only. ISO 15765 (diagnostics and UDS over CAN) is future research; it runs on the same CAN hardware, so it can be added later with decoding alone. J1708/J1587 is out of scope because it needs different hardware (a separate serial transceiver on its own connector pins).

**Priorities:** message-based methods (section 2) are the primary goal. Timing and cadence methods (section 3) and below-message methods (section 4) are out of scope and listed for reference only.

**Known limits:** the prototype covers a single J1939 network at the 9-pin diagnostic port. Volvo and Mack trucks with their own engines use a 16-pin connector, and some 2016+ trucks carry powertrain traffic on a separate network; both are known limits.

## Message-based methods

Message content is the cheapest and most direct evidence: any device that transmits leaves a source address, and many announce what they are. These methods need only a SocketCAN interface. The logger listens to all traffic and sends only the identification requests described below.

| Method                           | What to watch                                                                                                                                                                                                                                                                                                           | Serves                               | Main challenge                                                                                                                                                                                                   |
|----------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Address claim and NAME           | PGN 60928 claims from a NAME or source address (SA) not in the baseline. The 64-bit NAME carries manufacturer code (11 bits), identity number (21 bits), function, vehicle system and instance fields                                                                                                                   | Detection and identification         | Some devices transmit without claiming. The logger sends a global Request for Address Claim after claiming and every 10 minutes, so it does not depend on catching claims as they happen. The NAME can be copied |
| Address-claim conflicts          | A known SA claimed by a new NAME, or a known NAME appearing at a new SA; logged with both NAMEs and the outcome, high severity when the contested address belongs to a vehicle ECU                                                                                                                                      | Detection                            | Only competing claims are visible; two devices using one SA without claiming are not                                                                                                                             |
| New source address               | Any frame whose SA is not in the baseline table of SA to usual PGNs. Off-board service tools conventionally use SA 249 (0xF9) and 250 (0xFA)                                                                                                                                                                            | Detection                            | Several tools share SA 249/250, so the SA alone does not tell them apart. Misses devices that never transmit                                                                                                     |
| All PGNs from an unrecognized SA | Each distinct PGN an unrecognized SA sends, with first-seen time, last-seen time and count; the first 100 requests kept in order. Control PGNs are flagged at first occurrence, with a running count after that: TSC1 (0), TC1 (256), XBR (1024), Commanded Address (65240), Reset (56832) and DM11 clear codes (65235) | Detection and identification         | The flag list must be maintained; a legitimate tool running a test may also send some control PGNs                                                                                                               |
| New PGN from a known address     | A known SA sending a PGN never seen from it during training; replies to requests excluded. Notice severity; high if the PGN is on the control list                                                                                                                                                                      | Detection                            | Misses impersonation that uses only PGNs the real ECU sends; false alarms from PGNs training did not see. Limited form, pending a check with ORNL for overlap with their existing tools                          |
| Request messages                 | PGN 59904 requests from a new SA: which PGNs (VIN 65260, engine hours 65253, distance 65248/65217, time/date 65254, component ID 65259, software ID 65242, ECU ID 64965), global vs. destination-specific, the first 100 kept in order, with counts                                                                     | Identification                       | Requests depend on the vehicle: a device only asks for what the truck does not already broadcast, so its pattern can differ between trucks                                                                       |
| Responses to a new destination   | ECU replies or transport-protocol sessions (TP.CM 60416, TP.DT 60160) addressed to an SA not seen before                                                                                                                                                                                                                | Detection                            | Indirect: shows a requester exists, not what it is. Global requests (DA 0xFF) get broadcast replies with no destination                                                                                          |
| Diagnostic messages              | Requests for DM1/DM2 (65226/65227), clear-code requests DM3/DM11 (65228/65235), memory access DM14 to DM16, and DM18 data security (54272)                                                                                                                                                                              | Identification (tool vs. ELD)        | Legitimate shop work looks the same as abuse. Needs vehicle context, such as stationary or moving                                                                                                                |
| Proprietary PGNs                 | Proprietary A (61184) and Proprietary B (65280 to 65535) from the new SA                                                                                                                                                                                                                                                | Identification (vendor)              | Logged but not interpreted. Only useful once a known device has been seen using them; the content is undocumented                                                                                                |
| Self-reported identity           | Component ID (65259), software ID (65242) and ECU ID (64965), requested by the logger from each new SA, and from every device during training                                                                                                                                                                           | Identification (make, model, serial) | Works only for devices that support these PGNs. The reported identity can be blank or false                                                                                                                      |

Because the logger can send requests, it can confirm a new device and ask it to identify itself instead of waiting. The limits become which devices answer, and whether their answers are true.

## Timing and cadence methods (out of scope)

PGNs can be monitored for frequency and cadence, and timing is the best fingerprint for devices that poll on a loop. Track statistics per (SA, PGN) pair, because the same PGN from different senders behaves differently.

| Method                         | What to measure                                                                                                                                                                                                                                                                                                              | Serves                              | Main challenge                                                                                                                           |
|--------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| Rate and period per (SA, PGN)  | Mean period and frames per time window, compared with the baseline (e.g., CCVS 65265 at about 100 ms)                                                                                                                                                                                                                        | Detection                           | Event-driven and engine-speed-dependent PGNs vary normally, so thresholds need per-PGN tolerances                                        |
| Jitter                         | Standard deviation of inter-arrival time                                                                                                                                                                                                                                                                                     | Detection                           | Bus load and arbitration delays add jitter unrelated to any new device                                                                   |
| Off-cadence responses          | Extra on-request replies from an ECU between its periodic broadcasts                                                                                                                                                                                                                                                         | Detection (someone is asking)       | Needs a clean baseline of each ECU's periodic schedule. Other on-board requesters cause the same effect                                  |
| First-seen and last-seen times | When a new SA or (SA, PGN) pair starts and stops                                                                                                                                                                                                                                                                             | Detection of connect and disconnect | Disconnection is inferred from silence, which also happens at key-off                                                                    |
| Polling-loop fingerprint       | Request interval, its jitter, and the order of requested PGNs (e.g., VIN, then component ID, then engine hours every N seconds)                                                                                                                                                                                              | Identification                      | Stable for ELDs; irregular for diagnostic tools driven by a technician. Clone devices may share one loop                                 |
| Clock skew                     | Drift of a periodic sender's timing against the logger's clock, estimated from message periodicity. Cho and Shin's CIDS fingerprints ECUs this way and detected attacks on a prototype and on real vehicles ([USENIX Security 2016](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/cho)) | Identification of a physical unit   | Needs a periodic sender and enough samples. Built for ECUs, not tested here on add-on devices. Cloaking attacks can copy a target's skew |

Timing features are statistics over a window, so they identify a device after it has been sending for a while, not at the first frame.

The logger must exclude its own requests, and the replies they trigger, from all timing statistics; otherwise it measures itself. Off-cadence responses are the most affected.

## Below-message methods (out of scope)

These methods can catch devices that message-level methods miss, including some listen-only ones, but each needs hardware beyond a standard CAN interface.

| Method                     | What to watch                                                                                                                                                                                                                                                                                      | Serves                                   | Main challenge                                                                                                                                                                                                                                                                                 |
|----------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Error frames at connection | Short bursts of bit, CRC or stuff errors when a device is plugged into a live bus or auto-detects 250k vs. 500k                                                                                                                                                                                    | Detection (when)                         | SocketCAN reports them only if error frames are enabled. Wiring faults and noise produce the same errors. Says nothing about what was connected                                                                                                                                                |
| Voltage fingerprinting     | CAN-H/CAN-L voltage profile of each transmitter. Viden identified the attacker ECU with a 0.2% false identification rate on a prototype and two vehicles ([Cho and Shin, CCS 2017](https://arxiv.org/abs/1708.08414v1)); Scission and VoltageIDS are related schemes                               | Identification of a physical unit        | Needs an oscilloscope-class front end: reported sampling rates range from 50 kS/s (Viden) to 2.5 GS/s (VoltageIDS) ([DUET, NDSS 2021](https://friends.cs.purdue.edu/pubs/NDSS21_Duet.pdf)). Profiles drift with temperature and supply, and retraining can be poisoned. Only sees transmitters |
| Connector or pin sensing   | Detect a device at the diagnostic connector itself, e.g., current draw on the connector's power pins or a presence signal. A Toyota patent application describes detecting a device connecting to the OBD port and reporting it ([US 2017/0208074](https://patents.justia.com/patent/20170208074)) | Detection, including listen-only devices | Requires hardware at or in series with the port, which changes the installation. Says nothing about what the device is. Not message-based                                                                                                                                                      |
| Bus electrical changes     | Shifts in bus load or termination when a device with its own transceiver is added                                                                                                                                                                                                                  | Detection                                | Small changes, easily masked by normal variation. General knowledge, not checked against a source                                                                                                                                                                                              |

Connector sensing is the only method here that can detect a device that never transmits. Since listen-only devices are out of scope, this project does not need it.

## ELDs vs. diagnostic tools

The methods apply to both, but cadence fingerprints suit ELDs best and request and diagnostic-message patterns suit tools best. The rows below are expected behavior to confirm on known-good devices; it varies by vendor and software.

|                      | ELDs                                                                                                                                                                                                                                                                                                                   | Diagnostic tools                                                                                           |
|----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| Connection pattern   | Plugged in long-term, active whenever the truck runs                                                                                                                                                                                                                                                                   | Minutes to hours, usually at a shop, vehicle often stationary                                              |
| What is on the bus   | The ELD itself                                                                                                                                                                                                                                                                                                         | Usually an RP1210 adapter driven by PC software, so the software decides the SA and NAME                   |
| Transmits?           | Usually. Colorado State research on ELDs notes they need read and write access to the ECM to get all required data ([Daily et al., VehicleSec 2024 slides](https://www.engr.colostate.edu/~jdaily/presentations/2024%20VehicleSec24%20ELDs.pdf)). A device that gets everything from broadcasts may not (out of scope) | Almost always: reading codes and parameters needs requests                                                 |
| Best methods         | Polling-loop fingerprint, requested-PGN set, first-seen and last-seen times                                                                                                                                                                                                                                            | New SA (249/250), DM messages, proprietary PGNs, opening request sequence                                  |
| Identification limit | The same research found many online ELDs were clones, with one device sold under more than 50 brands, so a fingerprint may identify the hardware but not the brand                                                                                                                                                     | Identifies the software, not the physical adapter; one adapter running two programs looks like two devices |

## Identifying diagnostic tool types

Classify a tool by what it does on the bus first, and by product only where a characterized fingerprint exists.

### Tool categories

Examples are general knowledge, and signatures are expected behavior to confirm.

| Category                             | Examples                                                                      | Expected signature on the bus                                                   |
|--------------------------------------|-------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| Code reader                          | Handheld J1939 readers                                                        | Fault reads (DM1/DM2), possibly clear codes (DM3/DM11). Short session, few ECUs |
| Multi-brand diagnostic               | Noregon JPRO, Nexiq, TEXA, Jaltest                                            | Discovery requests to all ECUs, then fault reads from each. Broad and shallow   |
| OEM engine service tool              | Cummins INSITE, Detroit DiagnosticLink, CAT ET, PACCAR DAVIE, Volvo Tech Tool | Concentrates on the engine ECU (SA 0). Proprietary PGNs and deeper services     |
| Subsystem tool                       | Bendix ACom, WABCO TOOLBOX, Allison DOC, Eaton ServiceRanger                  | Concentrates on one non-engine ECU, e.g. transmission (SA 3) or ABS (SA 11)     |
| Reprogramming or calibration session | OEM tools during a flash                                                      | Memory access (DM14 to DM16), security (DM18), long transfers to one ECU        |

A side finding for ELDs: Navistar's address list includes aftermarket telematics at fixed addresses (Omnitracs/Samsara at 128, Qualcomm/PeopleNet at 142), and notes that its own telematics module moves to address 75 when a customer-installed device has already claimed 74. That supports the assumption that many aftermarket devices claim addresses and so are visible to the logger.

## Challenges common to all methods

With listen-only devices out of scope, the main limits are the logger's own transmissions, training quality and spoofing.

1.  **Listen-only devices.** Out of scope. A device that reads only broadcast traffic leaves no trace in the messages, so the logger does not try to detect it.

2.  **Address conflicts.** To send requests the logger must claim an address. It uses an arbitrary-address-capable NAME, claims from 247 downward, skipping addresses seen in the baseline and a reserved list of addresses used by tools and telematics (starting with 128 and 142), and waits 250 ms after any claim before other traffic. On a loss it tries one more address, then sends "cannot claim" and goes receive-only. Conflicts involving other devices are logged as evidence.

3.  **Side effects.** Some requests are commands: requesting DM3 or DM11 clears fault codes. The logger sends only from a fixed allow-list of identification PGNs (address claim, Time/Date, VIN, component ID, software ID, ECU ID); the frames it may send are limited to Request, Address Claim, Acknowledgment (for NACKs) and TP.CM for the transfer handshake, and never anything that writes, clears or controls.

4.  **Bus load.** A global request makes every ECU answer at once, some with multi-packet replies. The logger requests sparingly: a global address-claim sweep after claiming and every 10 minutes, Time/Date and VIN at each session start, and identification requests sent to each new address. Each request gets one retry after 1.25 s and is not repeated in the session after a NACK or no response.

5.  **Transfer handshake.** Multi-packet replies to a request sent to one address arrive point-to-point (RTS/CTS), so the logger must answer the transfer handshake. The logger's own J1939 code does this over raw CAN sockets once it has claimed an address; the kernel J1939 stack is an optional later optimization.

6.  **Being seen.** An external device can see the logger's address claim and requests. A malicious device could notice it is being monitored and change its behavior.

7.  **Logger's own traffic.** The logger's address and the replies to its requests would look like a new device. It excludes them by tracking its current address through its own NAME.

8.  **Boot and wake gap.** Requests a device sends while the logger is booting or waking are lost. The logger sleeps at key-off, wakes on CAN activity and records wake and ready times; the address-claim sweep recovers the NAMEs of devices that claimed during the gap.

9.  **Clock.** Without a battery-backed clock, timestamps are unreliable. Each record carries the logger's clock in UTC with its validity and source (time since wake when no valid clock exists), and the vehicle's Time/Date.

10. **Reference-table licensing.** Function, vehicle system and industry group codes come from the licensed SAE J1939 Digital Annex. The logger decodes only make on the device, from a published manufacturer code list (still to be sourced), and leaves the rest to analysis.

11. **Bit rate and network.** Trucks run J1939 at 250 or 500 kbit/s at the diagnostic port, and connector colour does not reliably tell which: many trucks with the green 9-pin connector still run 250 kbit/s. Transmitting at the wrong rate would disturb the bus, so each session starts listen-only and confirms the rate first. Each session records the connector and network used.

12. **Bus-off.** If the logger's controller goes bus-off, an automatic restart could keep disturbing the bus. The logger stops transmitting and stays listen-only for the rest of the session.

13. **Stub length.** J1939-11 is reported to limit a stub to 1 m and all stubs to 3 m in total (figures from a secondary source, to be checked against J1939-14 and J1939-15); an ELD's own Y-cable plus the logger's tap can exceed this. The logger uses a purpose-built short tap, and installation checks that bus error counts do not rise.

14. **Power loss and storage.** Trucks cut power without warning. The logger writes append-only records synced frequently, runs a read-only root filesystem, and drops the oldest raw captures first when the card fills.

15. **Log review.** Shops connect tools often, so events can pile up unread. The maintenance laptop produces a summary report at each retrieval, and a status light stays on until high-severity events are reviewed. The retrieval schedule and reviewer are to be agreed with ORNL.

16. **Training and baseline.** Anything present during training becomes known-good permanently, so training is started manually with only approved devices connected, covers key-on, engine running and driving, and is confirmed by a person from an authenticated maintenance laptop. Every training and approval action is logged with operator and time, since anyone who can train the logger can make their own device known-good. ECUs that appear only in some vehicle states would cause false alarms, so a new device that claims within 10 s of the session's first frame, keeps sending all session and makes no diagnostic requests is logged separately as "vehicle ECU not in baseline" (still high severity); its NAME is checked during analysis.

17. **Shared and reused addresses.** Tools share SA 249/250, and an arbitrary-address-capable device may land on a different SA on different trucks. SA alone is not an identity.

18. **Vehicle-dependent behavior.** A device requests only what a given truck does not broadcast, so its fingerprint can change between makes, models and engine software.

19. **Spoofing.** NAME, request pattern and polling loop can all be copied. Clock skew and voltage are harder to copy, but both have published attacks (cloaking; voltage corruption in [DUET](https://friends.cs.purdue.edu/pubs/NDSS21_Duet.pdf)). The logger produces an inventory, not proof of identity. Flagging a new PGN from a known address catches some impersonation, but not a device that sends only what the real ECU sends.

20. **Clones and adapters.** Cloned ELDs share hardware across brands, and diagnostic adapters take on whatever identity the PC software gives them, so identification may stop at hardware family or software package.

## Summary

For a message-based logger that can send identification requests, the workable core is address claims, new SAs, observed requests and the logger's own identification requests. Timing and cadence methods would also fit the logger but are out of scope for this project; the rest need extra hardware.

| Method                                               | Fits the logger (only message-based rows are in scope)                         | Catches listen-only devices | Identifies                                                         |
|------------------------------------------------------|-----------------------------------------|-----------------------------|--------------------------------------------------------------------|
| Address claim and NAME                               | Yes                                     | No                          | Maker and serial-like ID, if claimed                               |
| Active identification requests                       | Yes                                     | No                          | Make, model, serial, software version, if the device supports them |
| Address-claim sweep                                  | Yes                                     | No                          | NAMEs of all claiming devices, every 10 minutes                    |
| Address-claim conflicts                              | Yes                                     | No                          | A device competing for a known address                             |
| New source address                                   | Yes                                     | No                          | Nothing beyond "new device"                                        |
| All PGNs from an unrecognized SA, with control flags | Yes                                     | No                          | Attempted control of the vehicle; more fingerprint detail          |
| New PGN from a known address                         | Yes                                     | No                          | A known address sending something it did not send in training      |
| Request messages                                     | Yes                                     | No                          | Device type, possibly model                                        |
| Responses to a new destination                       | Yes                                     | No                          | That a requester exists                                            |
| Diagnostic messages                                  | Yes                                     | No                          | Tool vs. ELD, type of work done                                    |
| Proprietary PGNs                                     | Yes                                     | No                          | Vendor, once a known example exists                                |
| Rate, jitter, off-cadence responses                  | Yes                                     | No                          | That something new is active                                       |
| Polling-loop fingerprint                             | Yes                                     | No                          | Device model or clone family                                       |
| Clock skew                                           | Yes, with precise timestamps            | No                          | Physical unit (unproven for add-on devices)                        |
| Error frames at connection                           | Yes, if error frames are enabled        | Sometimes                   | Only when a connection happened                                    |
| Voltage fingerprinting                               | No, needs a high-rate voltage front end | No                          | Physical unit                                                      |
| Connector or pin sensing                             | No, needs hardware at the port          | Yes                         | Only that a device is present                                      |

## Sources

- Cho and Shin, [Fingerprinting Electronic Control Units for Vehicle Intrusion Detection](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/cho), USENIX Security 2016 (clock skew, CIDS).

- Cho and Shin, [Viden: Attacker Identification on In-Vehicle Networks](https://arxiv.org/abs/1708.08414v1), ACM CCS 2017 (voltage fingerprinting).

- Purdue, [DUET: voltage corruption attack on voltage-based IDS](https://friends.cs.purdue.edu/pubs/NDSS21_Duet.pdf), NDSS 2021 (sampling-rate comparison of Viden, VoltageIDS, Scission).

- Toyota, [Access Detection of an Unauthorized Device](https://patents.justia.com/patent/20170208074), US patent application 2017/0208074 (OBD-port connection detection).

- Daily et al., [ELD research slides](https://www.engr.colostate.edu/~jdaily/presentations/2024%20VehicleSec24%20ELDs.pdf), VehicleSec 2024 (ELD read/write access, clones). Unverified: taken from a search excerpt; the file itself could not be opened. Confirm before citing it in a class deliverable.

- PGN numbers, SA 249/250 conventions and NAME field layout are from general SAE J1939 knowledge and should be checked against J1939-21, J1939-71, J1939-73 and J1939-81.

<!-- -->

- Navistar, [J1939 Data Link Source Address Information (IK0800351)](https://static.nhtsa.gov/odi/tsbs/2024/MC-11008340-0001.pdf), rev. 21, 2024, via NHTSA (aftermarket telematics addresses).
