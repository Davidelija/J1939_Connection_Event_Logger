# J1939 Event Logger Requirements

Nov 6, 2026 · @Vaughan

## Purpose and conventions

This doc lists every requirement identified so far for the J1939 diagnostic-port connected-devices event logger, drawn from the detection doc, the DG Beacon doc and the architecture page. It is the starting point for the V-model's requirements and verification steps.

- **Background docs:** "Beacon doc", "Detection doc" and "Architecture" in the Source column refer to the files in `docs/background/`: `beacon-application.md`, `detection-methods.md` and `architecture.html` (decision X11).
- **IDs** are grouped by area: SC scope and constraints, NP network participation, TRN training and inventory, DET detection, IDN identification, LOG event logging, STS status, retrieval and review, HW hardware and power, PLT platform (what any hardware running the logger must provide), LAP maintenance laptop tool.
- **Wording:** "shall" marks a requirement. Numbers in a requirement are defaults held in the versioned config file unless the requirement says otherwise.
- **Verification:** T test (measured on the bench rig or a truck), D demonstration (operated and observed), I inspection (of a file, log or the unit), A analysis. Bus-level tests use the second Beacon as an independent witness that records everything on the bus.
- **Status:** Agreed (decided in the design reviews), Depends (relies on an unconfirmed Beacon capability), TBD (needs a decision or a check, listed under Open items), Deferred (kept with its ID for future work and not built in the prototype; listed under Future work). Deleted IDs are not reused.

## Scope and constraints

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| SC-1 | The logger shall monitor J1939 traffic on CAN on a single J1939 network, accessed at the 9-pin diagnostic connector. | I, T | Agreed | Detection doc: Purpose and scope |
| SC-2 | The logger shall operate at 250 kbit/s and 500 kbit/s, detecting the rate on the bus (NP-1); connector colour does not set the rate. | T | Agreed | Beacon doc: Hardware stack 1 |
| SC-3 | The logger shall detect and identify external devices from message content (message-based methods). Parent requirement, verified through the DET and IDN requirements. | T | Agreed | Detection doc: Message-based methods |
| SC-4 | The logger shall not disrupt the vehicle network: bus error counts shall not rise with the logger connected. | T | Agreed | Detection doc: Non-disruptive constraint |
| SC-5 | The logger shall leave the diagnostic port usable: an ELD or service tool shall still plug into the tap's pass-through port. | D | Agreed | Beacon doc: Hardware stack 2 |
| SC-6 | The logger software shall be written for Linux and SocketCAN so it can move from the DG Beacon prototype to a smaller in-vehicle logger. | I, A | Agreed | Beacon doc: Prototype platform |
| SC-8 | The logger software shall run unchanged on desktop Linux against a virtual CAN interface (vcan0), replaying recorded traffic with canplayer, for development and testing. | D | Agreed | Beacon doc: Software stack |
| SC-9 | The logger shall drop no frames at 60% bus load on a 500 kbit/s bus for 30 minutes with 2 s bursts at 100% load. A 100% load run of 10 minutes shall be performed and its drop count, CPU use and memory use reported, but it is not a pass criterion. CPU use, memory use and drop count from the 60% run shall be recorded in the test report and the transition overview, to size other hardware (PLT-7). | T | Agreed | Decision D4 |
| SC-10 | A 24-hour bench soak shall replay recorded traffic with a scripted connection every hour and a key cycle every 6 hours. It passes with no restarts, memory use growing less than 10% after the first hour, dropped frames within the SC-9 limit and every scripted connection detected. Per-session tables shall have fixed size limits. (A 7-day soak is deferred.) | T | Agreed | Reliability review R6 |
| SC-11 | A bench scenario suite in bench/, one scenario per device type and edge case (the scenarios in tests/fixtures/, replayed on the bench rig), shall pass when every scripted connection is detected and correctly categorized within 2 s (DET-16) and a 24-hour baseline replay produces no high events. Identification accuracy on characterized devices shall be reported, not used as a pass criterion. | T | Agreed | Reliability review R7 |
| SC-12 | decode and monitor shall be fuzz-tested in CI with random and malformed frames and transfers; no input shall stop the logger or exceed the DET-19 limits. | T | Deferred | Security review S3 |
| SC-12a | `decode` (transport reassembly, NAME decode) and `monitor` shall be tested in CI with generated malformed frames and transfers (property-based, Hypothesis): bad lengths, out-of-order and oversize transfers, bad NAMEs and floods of new addresses. No input shall raise an unhandled exception, stop the logger or exceed the DET-19 limits. | T | Agreed | Transition review X4 |

## Network participation

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| NP-1 | Each session shall start in listen-only mode and confirm the bit rate (250 or 500 kbit/s) from clean received frames before the logger transmits. | T | Depends (listen-only mode) | Beacon doc: Software stack 1 |
| NP-2 | After confirming the bit rate, the logger shall switch the channel to normal mode. | T | Agreed | Beacon doc: Software stack 1 |
| NP-3 | On bus-off, or on error-passive caused by its own transmit errors, the logger shall stop transmitting, stay listen-only for the rest of the session and log a fault. | T | Agreed | Beacon doc: Hardware stack 4 |
| NP-4 | The logger shall claim an address in the range 128 to 247, starting at 247 and working down, skipping addresses seen in the baseline or claimed so far this session and a configurable reserved list (initially 128 and 142). | T | Agreed | Detection doc: Address conflicts |
| NP-5 | The logger shall use an arbitrary-address-capable NAME in the on-highway industry group with every other field at its maximum (function 255, manufacturer code 2047), so it is higher than any NAME in the inventory and loses any address conflict with a vehicle device. | I, T | Agreed | Architecture: Address manager |
| NP-6 | The logger shall wait 250 ms after any address claim before sending other traffic. | T | Agreed | Beacon doc: Software stack 4 |
| NP-7 | On losing an address conflict, the logger shall try one more address; on a second loss it shall send Cannot Claim, go receive-only for the session and log it. | T | Agreed | Architecture: Address manager |
| NP-8 | The logger shall answer Request for Address Claim and NACK any other request addressed to it. It shall ignore a Commanded Address (PGN 65240) directed at its own NAME; it never changes address on command. | T | Agreed | Beacon doc: Software stack 4 |
| NP-9 | The logger shall transmit only its address claim, requests for the PGNs in requests.allow\_list (60928, 65254, 65260, 65259, 65242, 64965), and the responses J1939 requires of a node, including the transport-protocol handshake for replies addressed to it. It shall never transmit anything that writes, clears or controls, and shall provide no data to the network; the witness Beacon verifies this. The PGNs it may send are listed in transmit.allow\_list: Request (59904), Address Claim (60928), Acknowledgment (59392) for NACKs, and TP.CM (60416) for CTS, EOMA and Connection Abort (sent when it rejects a transfer addressed to it, DET-19). | T | Agreed | Detection doc: Side effects |
| NP-11 | The logger shall send a global Request for Address Claim after claiming and every 10 minutes. | T | Agreed | Beacon doc: Software stack 4 |
| NP-12 | The logger shall request vehicle Time/Date (65254) at session start and VIN (65260) at every session start and during training, as a destination-specific request to requests.vin\_sa (default 0, the engine), set at installation. | T | Agreed | Beacon doc: Software stack 4 |
| NP-13 | The logger shall request Component ID (65259), Software ID (65242) and ECU ID (64965) from each source address not held by a known NAME, and from every device during training; a known NAME at a new address is not asked again. | T | Agreed | Architecture: Request scheduler |
| NP-14 | Each request shall wait 1.25 s for a reply and retry once; the logger shall record the reply, NACK or no response, and shall not repeat a failed request in the same session. | T | Agreed | Architecture: Request scheduler |
| NP-15 | The logger shall exclude its own transmissions, and replies addressed to it, from detection. | T | Agreed | Detection doc: Logger's own traffic |
| NP-16 | The logger shall transmit at most 10 frames per second in total, with at most one outstanding request per destination; address-claim replies and NACKs shall go ahead of queued requests. Both limits are config parameters. | T | Agreed | Decision D9 |
| NP-17 | If neither bit rate is confirmed, the logger shall stay listen-only and keep trying; after 60 s it shall log a fault and show the fault state. It shall never transmit before a bit rate is confirmed. | T | Agreed | Review C2 |
| NP-18 | Any unexpected error in the transmit or request code, or a frame that would break the allow-list (NP-9) or the rate cap (NP-16), shall turn transmission off for the rest of the session and log a high fault; the offending frame is never sent. | T | Agreed | Reliability review R5 |
| NP-19 | (a) The service unit shall wait between restarts (RestartSec, initially 5 s) and cap restarts per time window. (b) After restart\_guard.count (3) unclean restarts within restart\_guard.window\_min (10 minutes), the next session shall start listen-only with transmit off: no address claim, sweep or requests. (c) The logger shall log a high fault ("restart loop; transmit disabled") and show fast blink until an operator runs `restart`. Detection continues listen-only. | T | Agreed | Final review F5 |

## Training and known-good inventory

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| TRN-2 | During training, the logger shall record the NAME, addresses and PGNs of every connected device across key-on with engine off, engine running and driving, plus PTO where fitted. | D | Agreed | Beacon doc: Software stack 5 |
| TRN-3 | Training shall end automatically after a configurable timeout (initially 120 minutes) if not finished; recording then stops and the proposed inventory waits for `train finish`. | T | Agreed | Beacon doc: Training and device approval |
| TRN-4 | A trained inventory shall be applied only after an operator reviews and confirms it from the maintenance laptop; a rejected inventory shall not be applied. `train finish` asks whether to apply it. | D | Agreed | Beacon doc: Training and device approval |
| TRN-5 | An operator shall be able to approve a device from a logged connection, adding its NAME to the inventory without full retraining. | D | Agreed | Beacon doc: Training and device approval |
| TRN-6 | The inventory shall be versioned at each confirmed training or approval, tied to the vehicle's VIN, and exported as a machine-readable file. | I | Agreed | Architecture: Known-good inventory |
| TRN-7 | Each inventory entry shall hold a permanent entry ID, the raw NAME and decoded fields, make, model, addresses and vehicle states seen, category, self-reported identity, PGNs normally sent, requests made (for approved external devices), and how and when it was added. | I | Agreed | Architecture: Known-good inventory |
| TRN-9 | Until a confirmed inventory exists, the logger shall run in untrained mode: record every device as unrecognized, send identification requests, mark the session header untrained, cap severity at notice, and show the needs-training state. | T | Agreed | Decision D6 |
| TRN-10 | (a) An operator shall be able to approve a single PGN, sent or requested, for a single known or approved device (by NAME), by running `approve` on the logged new-PGN event, with a reason. (b) Approving a control PGN (DET-9) shall show a warning line in the confirmation prompt. (c) Approved control PGNs are still counted in the device's records but not flagged. (d) The logger shall add the PGN to that device's approved list, save a new inventory version and log an approval record of kind PGN sent or PGN requested. (e) A notice address\_change can be approved the same way with `approve <event-id>`, which adds the address to that entry's addresses (a new inventory version), so it stops recurring. | T | Agreed | Decisions P1–P5, X42 |
| TRN-11 | The logger shall never add devices, PGNs or addresses to the inventory automatically; every addition comes from a confirmed training or an operator approval. | T | Agreed | Decision P4 |
| TRN-12 | At train finish, the logger shall report the conditions covered (key-on engine off, idle, driving, PTO), detected from engine speed and vehicle speed on the bus, with PTO taken from Power Takeoff Information 1 (PTO1, PGN 65264), engaged when Power Takeoff Speed (SPN 186) is above zero, when the truck sends it and otherwise declared by the operator, and the PGNs recorded per ECU in each condition. | T | Agreed | Decision T1 |
| TRN-13 | Inventory entries shall keep PGNs recorded in training separate from PGNs approved later, each later approval with its reason and date. The inventory shall record the vehicle configuration (make, model, year, engine, software level) so fleet profiles can be added later. | I | Agreed | Decisions P2, A1 |
| TRN-14 | (a) An operator shall be able to remove a device or vehicle ECU from the inventory by entry ID (`remove`), with a reason. (b) Removing a vehicle ECU recorded in training shall show a warning line in the confirmation prompt. (c) The logger is never part of the inventory; sweeps list it separately. (d) The logger shall save a new inventory version, apply it from the next session, retire the entry ID and log an inventory\_remove record. (e) When the device next appears it is classified as new. | T | Agreed | Usability review U8 |
| TRN-15 | An operator shall be able to remove one trained or approved PGN, sent or requested, from a device's inventory entry (`remove --pgn`), with a required reason. The logger shall save a new inventory version, apply it from the next session and log an inventory\_remove record; the PGN is then treated as new for that device (DET-12, or DET-9 for a control PGN). | T | Agreed | Usability review U8 |

## Detection

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| DET-1 | The logger shall match each address claim to the inventory by NAME and detect a NAME not in the inventory as a new connection. | T | Agreed | Detection doc: Address claim |
| DET-2 | The logger shall detect a source address that sends traffic without a claimed NAME. Addresses are matched to NAMEs each session from address claims and the address-claim sweep; the addresses stored in the inventory are hints only, except for an entry with no NAME (a device that never claims), whose address is its identity. Until the session's first sweep completes (sweep sent plus the 1.25 s request timeout), DET-2 and DET-3 decisions wait, with inventory addresses used as provisional matches; an address still sending without a matching NAME after the sweep is a DET-2 detection. If no sweep can be sent this session (no confirmed bit rate, claim lost, bus-off or restart loop), the wait ends detection.first\_sweep\_wait\_s (initially 10 s) after the logger is ready, and inventory addresses stay as matches for the session, refined by any claims heard. | T | Agreed | Detection doc: New SA; decision X42 |
| DET-3 | The logger shall detect replies sent to an address not held by a claimed NAME in the current session and not stored for a never-claiming inventory entry, excluding the global (255) and null (254) addresses and the logger's own address. | T | Agreed | Architecture: Scope; decision X42 |
| DET-4 | The logger shall detect and log address-claim conflicts, including the loss of its own claim. A known NAME claiming a new, uncontested address shall be logged as an info address\_change record, raised to notice if that address normally belongs to another known ECU; it is a conflict only when the address is contested. A move is confirmed when no frame arrives from the old address within detection.move\_grace\_s (initially 1 s) of the new claim. If the old address keeps sending, or both addresses answer a sweep with the same NAME, the logger shall log an address\_conflict with cause "same NAME at two addresses" at high severity. A new address is one that differs from the inventory's stored addresses for that NAME, or from the NAME's earlier address in the same session; each NAME and new-address pair is logged once per session. After a move is confirmed, any later frame from the old address before another NAME claims it, or both addresses answering a sweep with the same NAME, raises the same-NAME conflict, even if an address\_change was already logged. | T | Agreed | Detection doc: Address-claim conflicts; decision X42 |
| DET-5 | The logger shall detect NAMEs that appear or disappear between address-claim sweeps. | T | Agreed | Architecture: Connection detector |
| DET-6 | The logger shall end a connection after detection.silence\_end\_s (60 s) of silence from it while the bus is active, or at key-off, recording its last frame as the end time, and shall tell a disconnect apart from key-off. | T | Agreed | Beacon doc: Software stack 6 |
| DET-7 | For each unrecognized source address, the logger shall record each distinct PGN it sends with first-seen time, last-seen time and count. | T | Agreed | Detection doc: All PGNs from unrecognized SA |
| DET-8 | For each unrecognized source address, the logger shall keep its first 100 requests in order and count the requests dropped after that. | T | Agreed | Detection doc: All PGNs from unrecognized SA |
| DET-9 | The logger shall flag control PGNs, at first occurrence with a running count, when sent by a connection (an unrecognized or approved external device) or by a known device that did not send that PGN in training and has no approval for it: TSC1 (0), TC1 (256), XBR (1024), Commanded Address (65240), Reset (56832) and DM11 clear codes (65235), from a configurable list. | T | Agreed | Detection doc: All PGNs from unrecognized SA |
| DET-10 | The logger shall record diagnostic activity: DM1 (65226) and DM2 (65227) requests, DM3 (65228) and DM11 (65235) clear requests, DM14 (55552), DM15 (55296) and DM16 (55040) memory access, and DM18 (54272) data security. It shall also recognize extended transport protocol transfers (ETP, PGNs 51200 and 50944) without reassembling them, logging each in the connection record with sender, destination, PGN, bytes and completed or aborted, flagged as a memory transfer when it comes with DM14 to DM16 activity. | T | Agreed | Detection doc: Diagnostic |
| DET-11 | The logger shall log proprietary PGNs (Proprietary A 61184, Proprietary B 65280 to 65535) without interpreting their content. | T | Agreed | Detection doc: Proprietary |
| DET-12 | The logger shall flag, at notice severity, a known NAME sending a PGN not seen from that NAME during training (by address only for a device that never claims), and an approved external device requesting a PGN outside the set it requested during training. | T | TBD (ORNL check) | Detection doc: New PGN from a known address; decision X42 |
| DET-13 | The logger shall classify a vehicle ECU that is not in the baseline separately from an external device. A new device is a vehicle ECU not in baseline if it claims within 10 s of the session's first frame, keeps sending for the whole session and sends no diagnostic requests (any Request, PGN 59904, other than Request for Address Claim); otherwise it is an external device. Both are high severity; the category tells the reviewer which kind it is. The record names the rule applied, and analysis may reclassify from the NAME function code. | T, A | Agreed | Beacon doc: Software stack 8 |
| DET-14 | If the VIN received at session start differs from the inventory's VIN, the logger shall log a high-severity vin\_mismatch record, run the session in untrained mode and show the fault state. If no VIN reply arrives, the header shall record VIN unavailable and the session shall continue normally. | T | Agreed | Decision D7 |
| DET-15 | A connection shall be keyed by NAME for a device that claims (even if its address changes) and by source address for one that never claims; if a non-claiming device later claims, its NAME shall be linked to the same connection. A device returning after its connection ended shall start a new connection. | T | Agreed | Decision D14 |
| DET-16 | The connection\_start record shall be written and synced within 2 s of a new device's first frame, and the new-device indication shall turn on at the same time; identification results shall follow in their own record. For a device that never claims and is present at session start, the 2 s runs from the end of the first-sweep wait (DET-2). | T | Agreed | Decision D5 |
| DET-17 | The logger shall log each approved external device's connection start and end at info severity, with NAME, address and duration. | T | Agreed | Review C1 |
| DET-18 | (a) The logger shall classify a new device as a trailer device (notice severity) when its NAME is in the on-highway industry group with a vehicle system value of trailer (classify.trailer\_vehicle\_system). (b) It stays a trailer device only while it sends no diagnostic requests (as in DET-13), no control PGNs (DET-9) and no DM14 to DM18 memory access, and does not claim an address held this session by a known NAME, or one an inventory ECU normally uses. (c) If any of these happens, the logger shall reclassify it as an unrecognized external device (high) and log the reason. (d) Trailer devices get full connection records (LOG-7) and are not added to the inventory unless approved. A device can fake a trailer NAME; (b) limits it to broadcasting. | T | Agreed | Decision TR1 |
| DET-19 | The logger shall bound its use of bus input: at most limits.tp\_sessions multi-packet transfers open at once, transfers over the 1785-byte J1939 maximum rejected, transfer timeouts as in J1939-21, at most limits.pgns\_per\_conn distinct PGNs per connection, and at most limits.raw\_mb\_per\_session of raw captures per session. (A flood record for many new connections in one minute is deferred.) Malformed frames shall be counted and never stop the logger. 11-bit, remote and error frames shall be counted by type per session (and per connection where possible) and never decoded as J1939. | T | Agreed | Security review S3 |

## Identification

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| IDN-1 | The logger shall decode the NAME fields of every address claim and log them as raw numbers. | T | Agreed | Architecture: Reference tables |
| IDN-2 | The logger shall decode make from the manufacturer code using a manufacturer code list held in the device library file. The release ships the list empty with its format documented; the user loads a list they are licensed to use (candidate: the ISO 11783 list, which shares the J1939 code space); function, vehicle system and industry group shall be decoded during analysis from the SAE J1939 Digital Annex. | I | Agreed | Architecture: Reference tables |
| IDN-3 | The logger shall combine NAME fields, self-reported identity replies and the PGN record into a category, type, make and, where possible, model (from the manufacturer code, the self-reported identity, or a matched library entry that names them), with a confidence and the source of the identification. Make and model are taken from the self-reported identity first, then the manufacturer code (when a list is loaded), then a matched library entry. The record names the source used (make\_source). When sources disagree, the record keeps each value and notes the disagreement. A make or model that comes only from the library lowers the confidence by one step. | T, A | Agreed | Beacon doc: Software stack 8 |
| IDN-4 | Identification shall apply rules first, then a similarity score on requested-PGN sets against a library of characterized devices. When the best library matches are within identify.tie\_margin (initially 0.1 on the similarity score) and name different makes, identification reports the type only, with make and model unknown. A make or model that comes only from the library is reported as a profile match, for example "matches Acme CR-200 profile". An entry is scored only if the device's NAME function code is in the entry's functions (an entry with an empty functions list is scored for any function). The score is the Jaccard similarity (0 to 1) of the device's observed requested-PGN set against the entry's requests\_typical, minus 0.25 for each PGN seen that is in the entry's requests\_never or sends\_never, with a floor of 0; the tie margin applies on this 0-to-1 scale. When the best matches within the margin name different types, identification reports the broader category they share (for example "diagnostic tool"), lists the candidate types, and lowers the confidence by one step. A generic entry (make null) and a specific one count as different makes. The score uses the requests seen when identification completes. It is recalculated at connection end; if the type, make or model changes, `connection_end` carries the final identification (`final_identification`), otherwise the `identification` record stands. | T, A | Agreed | Beacon doc: Software stack 8 |
| IDN-5 | The library of characterized devices shall be a data file loaded at start-up, so devices can be added without changing code. It is built on the bench from known-good ELDs and diagnostic tools. Entries match on NAME function codes and on typical requested and sent PGNs, and may name a make and model (optional; left empty for a generic device type), with source addresses 249 and 250 only as a weaker hint. In the prototype the library is installed with the software release (install.sh), and its version is recorded in each session header. The team uses the devices it has; the findings report names each device and whether it built the library or only tested it (decision X32). | D | Agreed | Beacon doc: Bench setup |
| IDN-6 | The logger shall assign each event a severity of info, notice or high according to the severity rules in the log format. | T | Agreed | Beacon doc: Log format |
| IDN-7 | The device library, including the manufacturer code list, shall be changed only by pushing a new version from the maintenance laptop (library push). The logger shall validate it, save it as a new version and log a library\_change record, or reject it and log library\_rejected. | T | Deferred | Decision A2 |

## Event logging

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| LOG-1 | The logger shall write one event file per session, from wake (or power-on) to key-off, in JSON lines (one record per line). | I | Agreed | Beacon doc: Log format |
| LOG-2 | A session longer than 24 hours shall roll over to a new file part that continues the hash chain. | T | Agreed | Beacon doc: Log format |
| LOG-3 | Event files shall be written append-only and synced frequently (initially every 2 s), on an ext4-formatted card. Each record is written with one write() call to a file opened with O\_APPEND. | I, T | Agreed | Beacon doc: Hardware stack 6 |
| LOG-4 | Every event record shall carry a record number, type, severity, logger time in UTC to the millisecond, vehicle Time/Date, the previous record's hash, its own hash, and clock validity and clock source (LOG-16). `utc` is the time of the event (for a frame, its receive timestamp); each record also carries `written`, the time it was written. Events are referred to by event ID: session and record number, for example 142-4. | I | Agreed | Beacon doc: Log format |
| LOG-5 | Records shall be hash-chained with SHA-256 within and across sessions; the first record of a session shall carry the last hash of the previous session or part; after a power loss, the hash of its last complete record. An incomplete last line is never rewritten. The hash input is the UTF-8 bytes of the previous hash as 64 lowercase hex characters followed by the record without its hash field, serialized as compact JSON (separators , and :, keys in written order, non-ASCII characters as-is, numbers exactly as written). The first record on a new logger uses 64 zeros as prev. In the prototype (LOG-21 deferred), the first record on a replacement card also uses 64 zeros, and session\_start notes "new card"; the chain verifier reports this as a declared chain break, not tampering, and the laptop's last hash from the old card keeps the gap visible. The state file on internal flash (`state.json`: logger ID, last session number, last hash) is written atomically at each session start and after each session part. The next session number is one more than the higher of the state file's number and the newest session file on the card. A blank card with a state file is a new card (`new_card: true`, first `prev` of 64 zeros). A card with sessions but no state file, or a corrupt one, is an existing card in a new or reflashed logger: numbering and the chain continue from the newest session file on the card. A blank card with no state file is a new logger. If internal flash isn't writable (checked in step 2a), `install.sh` asks for the next session number when a new card is fitted. | T | Agreed | Beacon doc: Log format |
| LOG-6 | Each session shall begin with a header holding software, config, inventory and device library versions, VIN, bit rate and how it was confirmed, connector and network (from the config file, set at installation), wake cause and ready time, session counter, whether the previous session ended cleanly (with the cause from the diagnostic log, LOG-20, when there is one, and the bytes cut off after a power loss), the logger's address and NAME, the untrained flag, the installed operator key fingerprints, VIN status (match, mismatch or unavailable) and clock source. | I | Agreed | Beacon doc: Software stack 9 |
| LOG-7 | The logger shall write connection records for unrecognized external devices, vehicle ECUs not in the baseline, trailer devices and approved external devices; baseline vehicle ECUs get none. Records for unrecognized devices, vehicle ECUs not in the baseline and trailer devices hold start, end, duration and end reason, source address and NAME, identification results, the PGN and request records (DET-7, DET-8), DM activity and extended transfers (DET-10), control flags and severity. Records for approved external devices hold start, end, duration, end reason and any new PGNs sent or requested. | T | Agreed | Architecture: Event log |
| LOG-8 | The logger shall write the record types defined in docs/log-format.md, including operator actions (login, logout, training start and finish, approval, rejection, retrieval, review and clear, config change and rejection, device and PGN approval, inventory removal), each with operator and time. | I | Agreed | docs/log-format.md |
| LOG-9 | Address-claim sweeps shall be logged for the first sweep of a session and for any sweep that finds a change. | T | Agreed | Beacon doc: Log format |
| LOG-10 | The logger shall save raw CAN frames from 10 s before to 60 s after each new connection and each control-flag event, in `candump` log format, named by session, connection and event number (for example s000142\_c2\_e1.log). | T | Agreed | Beacon doc: Software stack 9 |
| LOG-11 | Retrieval shall never delete files. When space runs low, the logger shall remove retrieved raw captures first, then unretrieved raw captures, oldest first in each case; event files shall never be removed automatically. A reserve is kept for event files only (LOG-22). The status file shall list what has been retrieved. | T | Agreed | Beacon doc: Hardware stack 6 |
| LOG-12 | A session that did not end cleanly shall be flagged at the next start-up and shown as a gap in the summary. | T | Agreed | Beacon doc: Log review |
| LOG-13 | All settings shall be held in one versioned config file whose version is recorded in each session header. | I | Agreed | Beacon doc: Software stack 9 |
| LOG-14 | A standalone tool shall verify the hash chain across a set of session files and report the first broken or missing record, reporting an incomplete last line after a power loss as truncated rather than broken; it is used in testing and by the maintenance laptop at retrieval. | T | Agreed | Review of requirements |
| LOG-15 | The logger shall use a large kernel receive buffer, set with SO\_RCVBUFFORCE (or with net.core.rmem\_max raised by install.sh), record the size read back in session\_start, and record the kernel's per-socket dropped-frame count (SO\_RXQ\_OVFL) in each session\_end record. | T | Agreed | Decision D1 |
| LOG-16 | Records shall use UTC from the real-time clock when valid (not earlier than the software build date and no lost-power flag); otherwise records shall use the first vehicle Time/Date reply, kept by the logger as an offset, and before that records shall use time since wake. Every record shall carry clock\_valid and clock\_source. If vehicle time and the real-time clock differ by more than 5 minutes, the logger shall log a notice-severity fault and keep the real-time clock. Every timer (silence, sweeps, request timeouts, rate cap, key-off, roll-over, watchdog, restart-loop window) shall use the monotonic clock. The system clock is set only at boot from a valid real-time clock and never changed while the service runs; NTP and systemd-timesyncd are disabled. | T | Agreed | Decision D13 |
| LOG-17 | A session shall end after 30 s with no frames from any device; open connections shall then end with reason key-off. | T | Agreed | Decision D3 |
| LOG-18 | If the logger software restarts while power stays on, it shall start a new session whose header records the previous session as not ended cleanly, with reason software restart. | T | Agreed | Review C4 |
| LOG-19 | session\_start and every supporting file (inventory, config, device library, status) shall carry a format version. The verifier and report shall read every format version they know and refuse an unknown one with a clear message. Any change to a field or record type shall raise the format version and be listed in the log format's change history. | T, I | Agreed | Maintainability review M2 |
| LOG-20 | The logger shall keep a diagnostic log (errors, stack traces, restart causes) separate from the event files, size-capped and rotated (diag.max\_bytes, diag.files). It is not hash-chained and is not evidence. The next session header shall record the cause of an unclean previous end when the diagnostic log has one. | T | Agreed | Maintainability review M4 |
| LOG-21 | On a blank card the logger shall start with a chain\_start record (reason: new card) whose prev is 64 zeros, as for the first record on a new logger (LOG-5). The laptop shall link the new chain to the last hash it retrieved from that logger and report the link. Card replacement follows the quick guide: retrieve and verify, then swap the card. | T | Deferred | Maintainability review M8 |
| LOG-22 | The logger shall keep storage.event\_reserve\_mb of the card for event files only. At storage.warn\_pct card use it shall log a notice fault and flag the status file. When only the reserve is left it shall stop raw captures, log a high fault and keep writing event records. If the card is read-only or writes fail three times, it shall log a high fault and show the fault state. (Fallback to internal flash is deferred.) | T | Agreed | Reliability review R2 |
| LOG-23 | Inventory, config, library and status files shall be written to a temporary file, synced, then renamed into place. Version files are never overwritten, and leftover temporary files are ignored at start-up. The directory is synced after each rename. | T | Agreed | Reliability review R4 |
| LOG-24 | At first install the logger shall create its own Ed25519 signing key, kept on internal flash and never on the card; the laptop records the public key at install. The logger shall write a seal record signing the current chain hash at each session end, every seal.interval\_min, and within seal.after\_high\_s of every high event. The chain verifier shall check every seal against the recorded public key and report records after the last seal as an unsealed tail. | T | Deferred | Security review S1 |

## Status indication, retrieval and review

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| STS-1 | The logger shall show its state on one status light with three patterns: steady (recording, all good), slow blink (needs attention: new device, needs training, training running or card nearly full) and fast blink (fault); the light is off while starting and detecting the bit rate. Each state change shall also be logged, and `status` gives the detail. When conditions overlap, fast blink wins over slow blink and slow blink over steady; a VIN mismatch, transmission turned off and a restart loop (NP-19) show fast blink. | D | Depends (controllable LEDs) | Beacon doc: Status indication |
| STS-2 | The slow blink for a new device shall stay on until each high-severity event is reviewed and cleared from the maintenance laptop; each clearing shall be logged with operator and time. | D | Agreed | Beacon doc: Log review |
| STS-3 | The logger shall keep a status file holding its current state, unreviewed high events, faults, card use and card write totals where the card reports them, clock validity and source, untrained flag, files already retrieved, training coverage while training, and config and inventory versions, overwritten in place. | I | Agreed | Beacon doc: Log format |
| STS-4 | The logger shall not use wireless networks; Wi-Fi and Bluetooth shall be turned off at the driver level (STS-20). | I, D | Agreed | Beacon doc: Hardware stack 8 |
| STS-5 | Only an authenticated maintenance laptop shall retrieve logs, run training, approve devices, clear events or push configuration. Authentication shall use SSH keys over Ethernet or USB-Ethernet, one key per operator. The logger has a fixed address on its wired port (network.address, initially 192.168.250.1/24) and runs a DHCP server bound to that port only, so the laptop configures itself. The key used shall identify the operator in the log: OpenSSH ExposeAuthInfo gives the session the key fingerprint, which the logger maps to an operator name with the fingerprint-to-name file kept by release/keys.sh. | D | Agreed | Beacon doc: Training and device approval |
| STS-7 | At each retrieval, the maintenance laptop shall produce a plain-text report, shown on screen and saved as a file, with five sections in this order: events to review; new devices with make and type; changes to the inventory and config since the last retrieval, each with operator and reason, for the reviewer's sign-off (STS-8), detection-weakening config changes marked; sessions and gaps, with session counter and software, config and inventory versions; and the chain check result with the latest chain hash. Repeated events shall be grouped by device across sessions, and an events.csv file shall hold one row per event. | D | Agreed | Beacon doc: Log review |
| STS-8 | Logs shall be retrieved and reviewed on a schedule, by a reviewer, agreed with ORNL. | I | TBD (ORNL) | Beacon doc: Log review |
| STS-9 | (a) Configuration shall be changed only by pushing a new version from the maintenance laptop. (b) The logger shall validate it, save it as a new version, log a config\_change record with operator, old and new versions and changed fields, and apply it from the next session. (c) A change that weakens detection (a control PGN removed, a detection switch turned off, a shorter raw capture window, a longer silence time or a longer move grace) shall need --confirm and be logged as a high-severity config\_change marked as weakening detection. (d) A config with unknown or missing keys (listed in the record), or one that adds to requests.allow\_list or transmit.allow\_list, shall be rejected and logged as config\_rejected. | T | Agreed | Decision D12 |
| STS-10 | The logger shall count failed SSH login attempts and record the count in each session_end record and in the status file. (Blocking a source after repeated failures is deferred.) | T | Deferred | Review RD4 |
| STS-11 | `restart` shall restart the logger software, with a required reason; the next session records the restart (LOG-18). | T | Agreed | Decision RS1 |
| STS-12 | `retrain` shall archive the current inventory and return the logger to untrained mode on the same vehicle, keeping logs, config and the hash chain, with a required reason, logged as a reset record. | T | Agreed | Decision RS1 |
| STS-13 | `move` shall be refused until a verified retrieval covers every session. It shall then archive the old vehicle's logs and inventory on the card, return to untrained mode, require new connector and network settings, and log a reset record with a required reason; the hash chain continues. | T | Deferred | Decision RS1 |
| STS-14 | `wipe` shall be refused until a verified retrieval covers every session and shall need a second confirmation and a reason. It deletes logs, inventories and archives but keeps software and operator keys; the first record after it carries the last hash before the wipe. It is the only way event files are deleted, and only an admin key may run it (STS-21). | T | Deferred | Decision RS2 |
| STS-15 | `update` shall install a versioned release package after checking its checksum, next to the current release, and switch to it at the next session start, keeping the previous release. It shall be refused while training or while unretrieved high events exist, and needs a reason. The logger shall log a software\_update record (operator, old and new versions, checksum, reason). An update shall never change logs, inventories or archives on the card. The package shall be signed with the project release key (STS-22). Copying code by other means is not a supported update path. | T | Deferred | Maintainability review M1 |
| STS-16 | `rollback` shall switch to the previous release at the next session start, with a required reason, logged as a software\_update record marked rollback. | T | Deferred | Maintainability review M1 |
| STS-17 | `config push` shall run the logger's config validation on the laptop before sending. When a software update adds or renames settings, the release package shall carry a migration that writes a new config version, logged as config\_change with the update as its source. | T | Agreed (migration deferred) | Maintainability review M3 |
| STS-18 | The logger shall run under a systemd watchdog (watchdog.timeout\_s). The main loop and capture shall report that they are alive; if either stops, that is a hang. (Comparing capture's frame count with the kernel's receive count is deferred.) On a hang the logger restarts, and the cause goes to the diagnostic log and the next header (LOG-18, LOG-20). | T | Agreed | Reliability review R1 |
| STS-19 | At start-up the logger shall check that the card is writable, the config is valid, the inventory loads and the clock state is known. A corrupt inventory shall make the logger run untrained with a high fault; a corrupt config shall stop it with a fault. (Falling back to the last good version is deferred.) | T | Agreed | Reliability review R9 |
| STS-20 | The install procedure shall remove or change default accounts and passwords, turn off root SSH login and SSH password login, set ExposeAuthInfo yes, turn off wireless radios at the driver level, stop services the logger does not use, allow only SSH and DHCP on the wired port, disable NTP and systemd-timesyncd, and keep the root filesystem read-only. The installer confirms each step on the install checklist; the Beacon procedure is in docs/background/beacon-application.md (Hardening on the Beacon). (An automatic hardening check in `status` is deferred.) | T | Agreed | Security review S2 |
| STS-21 | There shall be two roles. Operator keys run only the laptop tool's commands through a forced command on the logger, with no shell and read-only file copy for retrieval. Admin keys, a separate small set, get a shell for first install, adding and removing operators, wipe and emergencies; every admin login is logged as an admin\_login record (notice). | T | Deferred | Security review S4 |
| STS-22 | `update` shall refuse a release package not signed with the project release key; the release public key is installed on the logger at first install. | T | Deferred | Security review S4 |
| STS-23 | (a) Only the logger service shall write the session file, inventory, config versions and status file. (b) A laptop command arrives over SSH and runs a logger-side command program, which sends the request to the service over a local Unix socket as JSON, with a protocol version that both sides check. (c) The service shall handle commands one at a time. (d) If the service is down, read-only commands (`status` from the status file, `retrieve`) still work, and changing commands are refused with "logger not running" and the next step. | T | Agreed | Final review F3 |

## Maintenance laptop tool

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| LAP-1 | The laptop tool shall run on Windows using Python 3 and the Windows OpenSSH client, without Windows-only code so Linux can be added later (Linux support is deferred). It is verified by a manual procedure on a Windows laptop. | D | Agreed | Decision L1 |
| LAP-2 | The tool shall provide these commands: status, train start, train status, train finish, events, approve, remove, clear, config show, config push, inventory show, inventory export, retrieve, report, restart and retrain (library push, move, wipe, update and rollback are deferred). | D | Agreed | Decision L2 |
| LAP-3 | (a) `train finish` and `events` shall list each item with a stable ID, NAME, address, make, category, PGNs sent and requests made. (b) Events are identified by session and record number (for example 142-37) and inventory entries by a permanent entry ID (for example E07) that is kept across inventory versions and never reused. (c) `approve`, `clear` and `remove` shall act on these IDs, never on list positions. (d) Every command that changes the logger shall show in plain words what will change, ask for a reason (at the prompt or with --reason), then ask y/N unless --yes is given. (e) Risky changes show a warning line in the same prompt. | D | Agreed | Decision L3 |
| LAP-4 | `clear` shall accept one or more event IDs and require one free-text reason (for example a repair-order number), stored in the review\_clear record. | T | Agreed | Decision L6 |
| LAP-5 | Retrieved logs shall be stored in one folder per logger, named by VIN; `retrieve` shall copy only new files, then verify the hash chain across the whole set and record the result in the logger's log. It shall also copy the diagnostic log (LOG-20). It shall make the retrieved folder read-only after verification; the laptop keeps each logger's last hash in its own state file. If a file to retrieve has the same name as one already retrieved but different content, `retrieve` keeps both, renaming the new one with a suffix, and reports it; it never skips it. | T | Agreed | Decision L4 |
| LAP-6 | Retrieval shall resume after a dropped connection: files already copied are skipped and partial files are copied again. | T | Agreed | Decision L8 |
| LAP-8 | Operator public keys (Ed25519, passphrase-protected) shall be installed and removed with release/keys.sh, which also keeps the fingerprint-to-operator-name file (STS-5); each session\_start shall list the installed operator key fingerprints. (operator\_add and operator\_remove records are deferred.) | T | Agreed | Decision L7 |
| LAP-9 | Retrieval of the session in progress shall copy complete records only, and the chain check shall report that session as in progress rather than broken. | T | Agreed | Review C5 |
| LAP-10 | (a) The laptop tool shall not set the logger's clock. (b) `status` is the home screen: one short block with state, VIN, session, unreviewed events, whether training is needed, card use and clock, ending with a Next step line that names the command to run. (c) `status` shall show the difference between the logger clock and the laptop clock and list the installed operator key fingerprints. | D | Agreed | Review RD1 |
| LAP-11 | `approve` shall require a reason and shall clear the event that triggered it in the same step, logged as an approval record with the reason. | T | Agreed | Review RD2 |
| LAP-12 | `report` and `inventory show` shall run on a retrieved folder without a logger connection. | D | Agreed | Review RD3 |
| LAP-13 | `inventory export` shall write the inventory as CSV (the inventory file itself is JSON). | D | Agreed | Decision E1 |
| LAP-14 | `train status` shall show, during training, the elapsed and remaining time, the conditions covered so far, the devices found and PGN counts per ECU; the status file shall hold the same coverage. | D | Agreed | Usability review U3 |
| LAP-15 | Every refused command shall say why and what to do (for example, move lists the sessions not yet retrieved). Each command shall have --help. (--dry-run is deferred.) The tool shall return a non-zero exit code when it refuses a command. | D | Agreed | Usability review U5 |
| LAP-16 | `clear --device` (entry ID or NAME) shall clear all open events of one device in one step with one reason, and `events` shall filter by severity, device and session. | T | Deferred | Usability review U6 |
| LAP-17 | Command output shall use plain words for what happened and for device categories (for example "new device", "ECU not in training", "trailer device", "approved device") rather than internal codes. | D | Agreed | Usability review U9 |

## Hardware, power and installation

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| HW-1 | The logger shall connect through a purpose-built short tap: a 9-pin splitter with a short leg to the logger (pass-through port per SC-5), adding under 0.5 m of stub including the logger cable. The figure is unverified until checked against J1939-14 and J1939-15; the total stub, including the vehicle's connector stub and any tool cable in the pass-through port, is an open item. | I, T | Agreed | Beacon doc: Hardware stack 2 |
| HW-2 | The logger shall add no termination: no terminator on the tap, and termination off on the logger's CAN channel. | I | Agreed | Beacon doc: Hardware stack 2, 4 |
| HW-3 | The logger shall run from the diagnostic connector's battery pin on 12 V and 24 V vehicles (6 to 32 VDC). | T | Agreed | Beacon doc: Hardware stack 3 |
| HW-4 | The logger shall operate from −40 to +85 °C, the range assumed for a device at the diagnostic port. | I | Agreed | Beacon doc: Hardware stack 9 |
| HW-5 | The logger shall sleep at key-off and wake on CAN activity, recording wake and ready times. Future research (decision X39); HW-8 (ready time) stays. | T | Deferred | Beacon doc: Hardware stack 3 |
| HW-6 | The logger shall resume cleanly after a cranking brownout. | T | Agreed | Beacon doc: Hardware stack 3 |
| HW-7 | The logger shall keep time across power loss with a battery-backed real-time clock, added as a module if the Beacon lacks one (PLT-3). | T | Depends (real-time clock) | Beacon doc: Hardware stack 7 |
| HW-8 | The logger's ready time after power-on and after wake shall be measured on the bench; the logger records it in each session header (LOG-6). | T | Depends (boot and wake-to-ready time) | Beacon doc: Open checks |
| HW-9 | The logger shall store logs on industrial-grade removable media (PLT-5), sized from the logging rate measured on the bench and the retrieval schedule (STS-8); 64 GB is the starting capacity on the Beacon. | I | Agreed | Beacon doc: Hardware stack 6 |
| HW-10 | The logger shall be mounted rather than hung off the port, and labeled with a status light legend and a do-not-unplug notice with a contact, so technicians do not remove it. | I | Agreed | Beacon doc: Hardware stack 9 |

## Platform requirements

What any hardware running the logger must provide, so a recipient can buy against it. How the DG Beacon meets each one is in the Beacon doc (Platform requirements on the Beacon); moving to other hardware is covered in `docs/porting.md`.

| ID | Requirement | Verify | Status | Source |
| --- | --- | --- | --- | --- |
| PLT-1 | The platform shall run Linux with SocketCAN and can-utils. | I | Agreed | Transition review X1 |
| PLT-2 | The CAN controller shall support listen-only mode, error-frame reporting, kernel receive timestamps and a readable per-socket drop count (SO\_RXQ\_OVFL) at 250 and 500 kbit/s, with termination switchable off. | T | Agreed | Transition review X1 |
| PLT-3 | The platform shall have a real-time clock with a backup battery. | I, T | Agreed | Transition review X1 |
| PLT-4 | The platform shall wake on CAN activity and, while asleep, draw little enough not to drain the battery over about 3 months parked (starting estimate 1 mA or less at 12 V). Future research (decision X39). | T | Deferred | Transition review X1 |
| PLT-5 | Storage shall be removable, industrial-grade (rated for continuous writes) and ext4-formatted, with the capacity in HW-9; install.sh refuses any other filesystem. | I | Agreed | Transition review X1 |
| PLT-6 | The platform shall run the Python version pinned in `pyproject.toml` and install the release bundle without internet access. | I, D | Agreed | Transition review X1 |
| PLT-7 | CPU and RAM shall be at least the figures measured in SC-9 on the Beacon, plus 50% headroom. | A | TBD (figures from SC-9) | Transition review X1 |
| PLT-8 | The platform shall run systemd with watchdog support and drive one indicator (LED or USB light) for STS-1. | I, T | Agreed | Transition review X1 |

## Constraints and assumptions

- The DG Beacon is a development and test platform only, not a permanent fleet installation (formerly HW-11). The goal is a hand-over proven on the Beacon. If a Beacon check fails or time runs out, the build proven on vcan is handed over with the Beacon results achieved so far, and each gap recorded (decisions X9, X12).
- The prototype covers one vehicle configuration at a time; connector type and network are set in the config file at installation.
- Software is Python 3 throughout. Frame capture is a separate module with a frames-in, timestamped-records-out interface, so it can be rewritten in C if the SC-9 bench test drops frames (decision D1). Capture reads SocketCAN with Python's standard socket module; python-can is only an optional input method in the platform layer (decision X22).
- Hardware-specific code lives only in the platform layer (`src/j1939logger/platform/`). Any hardware that meets PLT-1 to PLT-8 runs the logger once that layer is implemented for it and acceptance tests A1 to A8 pass (decision X2).
- The maintenance laptop tool is a Python command-line program using SSH; it also builds the summary report and runs the chain verifier (decision D2).
- The logger is deployed by copying a tagged release bundle over SSH and running `install.sh`, and runs as a systemd service that starts at boot and restarts on failure (decision H1).

## Deliverables

- **User manual** (docs/user-manual.md) with a printable quick card appendix, following the outline in the hand-off: getting started, everyday use, less common tasks, for analysts, admin, and reference. It is started as a skeleton in build step 1 and filled in at each step (decision X7). It replaces the separate install procedure, operator quick guide and training checklist (decision T2, review U2).
- **Transition overview** (docs/transition.md): 2 to 3 pages written for the recipient: what the prototype does and its status, what was verified and where, the core profile (the Demo subset), what the recipient must obtain, getting started, known limits, decisions left to the recipient, the licence, and a statement that no support continues after the semester (decision X8).
- **Porting guide** (docs/porting.md): the platform interface, the desktop and Beacon implementations as references, and acceptance tests A1 to A8 to run on new hardware (decision X2).
- **Transmit statement:** one page listing everything the logger transmits, for fleet approval and OEM or ELD questions. It states that the logger's NAME uses manufacturer code 2047, which is unassigned, so an OEM does not go looking for the manufacturer (formerly SC-7).
- **Test report:** the verification matrix (docs/verification.md), with every requirement's method, test or procedure step, where it was verified (vcan, Beacon or not verified), result, date and evidence file, updated at every build step (a CI check fails if a T requirement has no test). Every hardware-relevant T requirement needs a Beacon (or backup platform) result; under the vcan fallback each gap is recorded instead: Where not verified, or Result not supported on the Beacon, with the reason (decisions X9, X12). It also holds acceptance test results A1 to A8 on the Beacon, the SC-9 CPU, memory and drop figures, the SC-11 scenario suite, the SC-10 24-hour soak and the wake and ready times (sleep is future research, decision X39) (reviews M6, R6, R7; decision X5).
- **Findings report** (docs/findings.md, decision X30): the validation report, about 2 pages, answering whether a logger at the diagnostic port can detect and identify connected devices from their messages, and how well. Written in step 9 at whatever cut-line tier is reached, to the outline in docs/findings-report-spec.md; data in docs/findings-data/, produced by the scripts in tools/findings/.
- **No-hardware demo** (demo/run\_demo.sh, decision X31): brings up vcan0, runs the logger and the laptop tool against the session 142 scenario and verifies the chain; runs in CI; needs a Linux machine or VM.
- **Recorded walkthrough** (optional, decision X34): a 15 to 20 minute screen and bench recording, made in step 9 after the required documents if time allows.
- **Release** (decision X6): a tagged version (v0.x) with CHANGELOG.md; release/ with a wheelhouse pinned by hash, install.sh and the systemd unit, for installing without internet access; LICENSE (MIT, decision X10); a PDF snapshot of docs/ for each tag. The repo's docs/ is the authoritative source and, from Tuesday, Nov 10, 2026, the only copy (decision X19). The background docs (Beacon doc, detection doc, architecture page) are handed over from docs/background/ (decision X11). The Claude Docs, Word and text versions are frozen working copies, marked superseded as of Nov 10, 2026, and are not handed over. No licensed content ships: no SAE Digital Annex tables and no manufacturer code list.
- **Developer docs:** the repo README (build, test and run on vcan0, pinned dependency list), the hand-off, requirements, log format, the threat model (docs/threat-model.md: assets, attackers, entry points and the requirement or known limitation covering each), docs/errors.md, every expected error and how the logger handles it (decision X36), and docs/reviews.md, one human-review line per build step (reviews M7, S9; decision X7).
- **Software deliverables:** the device library data file built from the bench characterization (IDN-5) and the hash-chain verifier tool (LOG-14).

## Demo subset

The minimum set for the class demo, and the core profile named in the transition overview. Everything else is built if time allows. The cut line (hand-off, Build plan) builds the functional core first, then the hardware evaluation. The goal is a hand-over proven on the Beacon, with the vcan build and the Beacon results achieved so far as the fallback (decisions X12, X13).

**Functional core** (built and tested on vcan; tier 1):

- **Capture and transmit:** SC-1, SC-2, SC-4, SC-8, NP-1 to NP-9, NP-11 to NP-19.
- **Detection and identification:** DET-1, DET-2, DET-6 to DET-9, DET-13, DET-16, IDN-1 to IDN-3.
- **Logging:** LOG-1, LOG-3 to LOG-7, LOG-13, LOG-14, LOG-17.
- **Training and inventory:** TRN-2, TRN-4, TRN-5, TRN-9.
- **Laptop tool:** LAP-2 (status, train start, train finish, events, approve, clear, retrieve, report), LAP-3, LAP-5, STS-23.
- **Tests:** SC-12a.

**Hardware evaluation** (on the Beacon, or the backup platform; tiers 2 and 3):

- **Tier 2:** acceptance tests A1 to A4, including the SC-9 load test.
- **Tier 3:** acceptance tests A5 to A8, then the SC-10 24-hour soak and the SC-11 scenario suite.

## Referenced specifications

| Spec | What it defines |
| --- | --- |
| `docs/log-format.md` | Authoritative schema: files and layout, fields on every record, record types, severity rules, supporting file contents |
| Example files, session 142 (`s000142_20261106T140211Z.jsonl`, `s000142_c2_e1.log`, `s000142_c2_e2.log`, `lib-v1.json`, `inv-v2.json`, `cfg-v3.json`, `status.json`) | Worked examples of every file the logger writes |
| `docs/background/architecture.html` (and `.png`) | Module breakdown, data flow and transmit path |
| `docs/background/detection-methods.md` | Definition of each detection method and its challenges |
| SAE J1939-13, -21, -71, -73, -81 | Connector, data link and transport protocol, PGN definitions, diagnostic messages, address claiming |

## Configuration parameters

Defaults are those in `cfg-v3`. Each parameter lives in the versioned config file (LOG-13). The table and cfg-v3 hold exactly the same keys; settings for deferred features are added when those features are built.

| Parameter | Default | Used by |
| --- | --- | --- |
| `can.interface` | can0 | SC-6 |
| `can.termination` | off | HW-2 |
| `can.bitrates` | 250000, 500000 bit/s | SC-2, NP-1 |
| `can.bitrate_check_frames` | 300 clean frames | NP-1 |
| `can.bitrate_fault_s` | 60 s | NP-17 |
| `can.rx_buffer_bytes` | 1048576 (raise if the bench test drops frames) | LOG-15 |
| `address.name` | 0x9FFEFFFFFFE00001 (the last digits are the identity number, unique per unit) | NP-5 |
| `address.claim_from`, `address.claim_down_to` | 247, 128 | NP-4 |
| `address.reserved` | 128, 142 | NP-4 |
| `address.claim_wait_ms` | 250 ms | NP-6 |
| `address.claim_retries` | 1 | NP-7 |
| `requests.allow_list` | 60928, 65254, 65260, 65259, 65242, 64965 | NP-9 |
| `requests.vin_sa` | 0 (the engine), set at installation; changing it does not weaken detection | NP-12 |
| `requests.sweep_interval_min` | 10 min | NP-11 |
| `requests.timeout_s`, `requests.retries` | 1.25 s, 1 | NP-14 |
| `transmit.allow_list` | 59904, 60928, 59392, 60416 | NP-9 |
| `transmit.max_frames_per_s` | 10 | NP-16 |
| `transmit.max_outstanding_per_dest` | 1 | NP-16 |
| `detection.silence_end_s` | 60 s | DET-6 |
| `detection.requests_kept` | 100 | DET-8 |
| `detection.control_pgns` | 0, 256, 1024, 65240, 56832, 65235 | DET-9 |
| `detection.known_device_new_pgn` | true | DET-12 |
| `detection.move_grace_s` | 1 s; validation rejects more than 5 s | DET-4 |
| `detection.first_sweep_wait_s` | 10 s | DET-2 |
| `classify.wake_window_s` | 10 s | DET-13 |
| `identify.tie_margin` | 0.1 (similarity score) | IDN-4 |
| `classify.trailer_vehicle_system` | 2 (confirm against J1939 Appendix B) | DET-18 |
| `limits.tp_sessions`, `limits.pgns_per_conn`, `limits.raw_mb_per_session` | 32, 2000, 200 MB | DET-19 |
| `session.end_silence_s` | 30 s | LOG-17 |
| `logging.session_rollover_h` | 24 h | LOG-2 |
| `logging.sync_interval_s` | 2 s | LOG-3 |
| `logging.hash` | sha256 | LOG-5 |
| `logging.raw_before_s`, `logging.raw_after_s` | 10 s, 60 s | LOG-10 |
| `storage.event_reserve_mb`, `storage.warn_pct` | 500 MB, 90% | LOG-22 |
| `diag.max_bytes`, `diag.files` | 10 MB, 5 | LOG-20 |
| `watchdog.timeout_s` | 30 s | STS-18 |
| `restart_guard.count`, `restart_guard.window_min` | 3 restarts, 10 min | NP-19 |
| `network.address` | 192.168.250.1/24, set at installation | STS-5 |
| `clock.max_skew_min` | 5 min | LOG-16 |
| `training.timeout_min` | 120 min | TRN-3 |
| `training.states` | key-on engine off, idle, driving, PTO | TRN-2, TRN-12 |
| `install.connector`, `install.network` | set at installation | LOG-6 |

## Enumerated values

| Field | Allowed values |
| --- | --- |
| Severity | info, notice, high |
| Category | vehicle ECU in baseline, vehicle ECU not in baseline, trailer device, external device (approved), external device (unrecognized) |
| Connection end reason | silence, key-off, power loss, software restart, watchdog restart, session roll-over. Silence is after detection.silence\_end\_s; power loss is recorded at the next start-up |
| Logger state | starting, detecting bit rate, recording, training, needs training, fault; needs training is untrained mode; new device shown as a separate indicator |
| Request outcome | reply, NACK, no reply |
| Identification source | NAME, self-reported reply, request pattern, or a combination |
| Confidence | high, medium, low |
| Clock source | rtc, vehicle, elapsed |
| Make source | self-reported, manufacturer code, library, none |
| Classification rule | in inventory, wake timing, request activity, NAME. NAME is used in analysis only |
| VIN status | match, mismatch, unavailable |
| Previous session end | clean, power loss, software restart, watchdog restart, software update |
| Reset mode | restart, retrain, move, wipe |
| Approval kind | device, PGN sent, PGN requested, address; removals use remove device, remove PGN sent, remove PGN requested |
| Role | operator, admin |

## Not required (out of scope)

These were considered and left out; they are not requirements for this project.

- Timing and cadence detection (PGN frequency, intervals, clock skew)
- Below-message detection (voltage fingerprints, connector or pin sensing, bus electrical changes)
- Listen-only devices that never transmit
- Identifying devices that never claim an address, beyond the PGNs they send
- Devices sharing a source address without claiming it, and other atypical timing from a known address
- Networks other than the single J1939 network at the 9-pin port, including 16-pin connectors and separate powertrain networks
- Interpreting proprietary PGN content
- Physical tamper protection (seals, locked enclosure, card slot covers)
- J1708/J1587 (needs different hardware)
- ISO 15765 diagnostics over CAN (future research: same hardware, decoding only)

## Known limitations

These are accepted limits of message-based detection, not requirements:

- A device that copies a known NAME and address (spoofing) looks like the known device; DET-12 and DET-4 may catch it only if its traffic or claims differ.
- A clone of an approved device is treated as that device.
- Listen-only devices that never transmit cannot be seen.
- Logs on a removed microSD card are readable and not encrypted. They are hash-chained but not signed (LOG-24 deferred), so someone holding the card could rewrite records not yet retrieved and recompute the chain; the last hash kept on the laptop at each retrieval shows tampering with anything already retrieved.
- Operators have a shell on the logger (STS-21 deferred); their tool actions are logged, but direct file edits are not.
- Software is deployed from a release bundle copied over SSH and is not signed (STS-15, STS-22 deferred); the software version is recorded in every session header.
- A failing card stops event recording with a high fault (internal flash fallback deferred).
- Up to 2 s of records can be lost on a sudden power loss (the sync interval); connection\_start is synced at once (DET-16), so the fact that a device connected is not lost.
- A device that copies the NAME of a known device absent this session, at a free address, is recorded as a move (info or notice), because nothing contests it; DET-12 (new PGNs from that NAME) and the control-PGN flags are the backstop.
- A clone that behaves like a characterized product matches that product's library profile and is reported as a profile match under its brand; the record shows the make came from the library.
- The prototype is proven on the platform named in the transition overview (the DG Beacon, the backup platform, or vcan only). Other hardware needs the platform layer implemented (docs/porting.md) and acceptance tests A1 to A8 passed before its results can be trusted.

## Future work

Not part of the prototype build:

- **Fleet profiles:** merge confirmed inventories from trucks of the same configuration, so a new truck needs only a short training to learn its NAMEs (decision A1). The inventory already records vehicle configuration (TRN-13).
- **Onboard screen:** a display on the logger for training, approvals and review in place of the maintenance laptop.
- **ISO 15765:** diagnostics over CAN (same hardware, decoding only).
- **Low-power sleep for unattended installation** (decision X39): no battery drain over about 3 months parked; starting estimate 1 mA or less at 12 V (1 mA × 2,160 h ≈ 2.2 Ah, under 1% of a 300 Ah bank). Needs a power controller that fully cuts power and wakes on CAN or ignition; the Beacon (about 1.6 A) and typical single-board computers can't meet it alone. Covers HW-5 and PLT-4.
- **Forced command per operator key** (decision X24): operator keys run only the command program, with no shell, alongside deferred STS-21.
- **Two-person approval:** a second operator to confirm control-PGN approvals and removal of trained ECUs (security review S6).
- **Deferred requirements (scope reduction, Nov 7):** HW-5 and PLT-4 (future research, X39), LOG-21 (new-card chain start), LOG-24 (signed seals), IDN-7 (library push), STS-13 (move), STS-14 (wipe), STS-15 and STS-16 (update and rollback), STS-17 migration, STS-21 (roles), STS-22 (signed releases), LAP-16 (clear by device, event filters), SC-12 (full fuzz campaign; the basic malformed-input tests in SC-12a are built) and STS-10 (failed-login counting); plus the deferred parts of SC-10 (7-day soak), STS-18 (frame-count hang check), STS-20 (automatic hardening check), LOG-22 (internal flash fallback), LAP-15 (--dry-run), LAP-1 (Linux) and DET-19 (flood record).

## Open items affecting requirements

The Beacon checks in this table are run on the unit in build step 2a, before any transmit code, as a go/no-go (decisions X18, X41); each result is recorded here and in docs/verification.md.

| Item | Affects | Resolution |
| --- | --- | --- |
| Kernel J1939 support on the Beacon | NP-4 to NP-9, NP-15 | Optional: raw CAN sockets with the logger's own J1939 handling are the default; kernel J1939 may be adopted later as an optimization |
| SocketCAN interfaces and transmit on the Beacon | SC-6, NP-2 | Check with `ip link show` in step 2a; if it fails, switch to the backup platform (X21); the vcan fallback (X12) applies if that also fails |
| Listen-only mode | NP-1 | Check supported controller modes in step 2a; if it fails, switch to the backup platform (X21); the vcan fallback (X12) applies if that also fails |
| Real-time clock | HW-7, LOG-4 | Power-cycle test; add a USB or I2C module if absent |
| Sleep and wake on CAN | HW-5 | Future research (decision X39): HW-5 and PLT-4 are Deferred; only wake and ready time are measured (HW-8, A6) |
| Boot and wake-to-ready time | HW-8, DET-1 | Measure; the address-claim sweep recovers devices that claimed during the gap |
| Controllable status LEDs | STS-1 | Check `/sys/class/leds` or ask DG; otherwise a USB indicator or the status file |
| Control PGN numbers | DET-9 | Closed Nov 7: the numbers were checked; confirm once against J1939-71 and J1939-73 when the standards are available |
| New PGN from a known address | DET-12 | Check with ORNL for overlap with their work |
| Retrieval schedule and reviewer | STS-8 | Agree with ORNL; otherwise listed in the transition overview as a decision for the recipient |
| Stub limits at 500 kbit/s | HW-1 | Check J1939-14 and J1939-15, and state the total stub assumed, including the vehicle's connector stub and any tool cable in the pass-through port |
| Custom systemd service on the Beacon | H1 deployment | Check that a custom service can be installed and starts at boot |
| Python 3 on the Beacon | D1, all software | Check the installed version (DC-1 sets 3.9 as the floor until then) and whether the release bundle installs without internet; otherwise build a self-contained Python runtime |
| Trailer devices on the tractor's J1939 bus | DET-1, DET-13, DET-18 | Check on fleet trucks whether trailer devices or gateways appear as new NAMEs at the 9-pin port. North American trailer ABS normally uses power-line carrier (J2497), not the tractor's J1939 bus. Also confirm the NAME vehicle system value that marks a trailer (DET-18) |
| Writable internal flash and systemd watchdog on the Beacon | LOG-22, STS-18 | Check for a writable partition with 100 MB free (it also holds `state.json`, LOG-5) and that the systemd version supports the watchdog; otherwise a failing card is a high fault only, `install.sh` asks for the next session number when a new card is fitted, and the hang check runs as a separate supervisor process |
| Beacon default accounts, services and radios; cryptography package | STS-20, STS-21, LOG-24 | List accounts, listening ports, running DG services and radio drivers on the Beacon and confirm each can be turned off; check that the cryptography package installs, otherwise use a self-contained Python runtime (as for python-can) |
| Escalation contact and data-handling rules | User manual, STS-8 | Agree with ORNL who to contact about a suspicious device, and who may hold retrieved logs (they contain VINs and device IDs) and for how long; otherwise listed in the transition overview as decisions for the recipient |
| Manufacturer code list | IDN-2 | The release ships the list empty with its format documented; the recipient sources a list they are licensed to use (candidate: ISO 11783, which shares the J1939 code space). Until one is loaded, make is recorded as unknown with the raw code |
| Platform sizing figures | PLT-7 | Measured in SC-9 on the Beacon in build step 8 |
| DET-13 request rule | DET-13, DET-18 | Check against rig captures in build step 5. If genuine late-waking ECUs in the captures are labelled external devices, narrow "diagnostic request" to DM requests and memory access (DM14 to DM18) (decision X15) |
| Beacon go/no-go checks | SC-6, NP-1, NP-3, HW-2, LOG-15, PLT-1 to PLT-8, STS-5, STS-20 | Checked in build step 2a (decisions X18, X41): whether a DG service owns the CAN channels (stop DG services and try candump); berr-reporting and the TX/RX error-passive flags in error frames; restart-ms 0 honoured; termination switchable with ip link; net.core.rmem\_max can be raised, with root or CAP\_NET\_ADMIN; CPU architecture, cores, RAM and free space (uname -m, nproc, free -m, df -h); the USB-B port as USB-Ethernet; the card filesystem (lsblk -f); listening services (ss -tlnp), with FTP and the web server turned off. If SocketCAN or listen-only fails, switch to the backup platform (X21); the vcan fallback (X12) applies only if that also fails |
| Code licence | Release | MIT (decision X10); confirm with CSU and the instructor near project completion, before the first tag, and fill in the LICENSE names then (decision X40) |
