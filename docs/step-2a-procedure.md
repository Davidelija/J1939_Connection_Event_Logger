# Step 2a procedure: Beacon go/no-go

A step-by-step procedure for build step 2a (decisions X18, X41), written so that someone who has not worked on the logger can run it. It checks whether the DG Beacon can run the logger, using standard Linux tools only: no logger code runs, and nothing transmits on a vehicle. The bench is described in `docs/test-bench.md`.

**Time:** about half a day, plus a short second session for B4 if the `cryptography` wheel is not ready.
**People:** one person is enough (Vaughan Lynn or Elijah Umaru, or someone they ask). A second person may observe.
**Output:** a folder of evidence files and the results sheet at the end of this document, handed to the developers.

## 1. What decides go or no-go

Three checks decide whether the Beacon can be the logger:

| Check | What it proves | If it fails |
| --- | --- | --- |
| A1 | The Beacon's CAN channels are SocketCAN interfaces | **No-go** |
| A3 | A channel can listen without acknowledging frames (listen-only mode) | **No-go** |
| A4 | A channel can transmit in normal mode | **No-go** |

On a no-go, stop, record the results so far, and tell the project: the hardware tier switches to the backup platform (decision X21, `docs/porting.md`). Every other check only records a fact; when one fails, write down the fallback named in that check and carry on.

## 2. Before the day

Tick each item before you start.

- [ ] **Root access to both Beacons**: the default account and password from DG, or from whoever set the units up. Almost every check needs root.
- [ ] **Bench wired as in `docs/test-bench.md`**: Beacon 1 and Beacon 2 on one bus with a 120 Ω terminator at each end. With the power off, the resistance between CAN-H and CAN-L reads about 60 Ω.
- [ ] **Bench supply** set to 12 V, with an output switch you can use to power-cycle Beacon 1.
- [ ] **Laptop** with Ethernet, a USB cable for the Beacon's USB-B port, an SSH client, and the repository checked out.
- [ ] **The Beacon's datasheet** (for G1) and, if possible, a DG contact for questions about LEDs and DG's own services.
- [ ] **A card of the planned type** (industrial microSD, formatted ext4) in Beacon 1.
- [ ] **A USB stick** with two folders, prepared on the Linux machine:
  - `wheels/`: the logger's wheel (distribution `j1939-logger`, imported as `j1939logger`). The logger is pure Python with no run-time dependencies (`dependencies = []` in `pyproject.toml`), so one wheel works on any CPU. Build it in the repository with `python3 -m pip wheel --no-deps -w wheels .`
  - `crypto/`: the `cryptography` wheel for the Beacon's CPU and Python. This needs B1 and B2 first; if you don't know them yet, leave it for a second short session.
- [ ] **No network cable** to the Beacon, except the laptop link in F1.

## 3. Run it with the script (DC-29)

`tools/step2a.py` runs this procedure from the laptop over SSH: the same commands, in the order of section 4. It saves each check's output to `docs/test-evidence/2a_<date>/`, suggests Pass, Fail or Gap where a machine can judge, asks you for the physical steps (disconnect Beacon 2, the power-off, plugging in the laptop, the datasheet and the tap), and writes `results.md`, the results sheet of section 12 pre-filled for you to confirm.

```sh
python tools/step2a.py --beacon1 root@<beacon-1> --beacon2 root@<beacon-2> --wheels wheels/ [--crypto crypto/]
```

- Set up SSH keys for both Beacons first (`ssh root@<beacon> true` must work without a password prompt).
- It asks you to type `BENCH` before the first frame is sent, and stops at a no-go (A1, A3 or A4).
- It copies the wheel folders to the Beacon with `scp`, so B3 and B4 need no USB stick.
- After the power-off, or on another day, continue with `--resume docs/test-evidence/2a_<date>`. Rerun single checks with `--only A7,C1`.
- At the end (or on Ctrl-C) it puts both CAN interfaces back to 250 kbit/s, normal mode, termination off, and removes its test units.

You can always run any check by hand as described below; the script only saves typing. Check every suggested result in `results.md` before handing it over.

## 3a. Conventions (by hand)

**Where commands run.** "B1#" means a root shell on Beacon 1; "B2#" a root shell on Beacon 2. Log in over SSH from the laptop, or on a console.

**Interface name.** `can0` below stands for the interface A1 finds. If it is called something else, use that name everywhere.

**Saving evidence.** On each Beacon, make a folder once:

```sh
mkdir -p /root/2a
```

Run every check's commands through `tee`, so the output is both shown and saved, one file per check. For example:

```sh
{ ip link show; ip -details link show can0; } 2>&1 | tee /root/2a/A1.txt
```

At the end, copy the folders to the laptop and put them in the repository as `docs/test-evidence/2a_B1_<date>/` and `docs/test-evidence/2a_B2_<date>/`:

```sh
scp -r root@<beacon-1-address>:/root/2a docs/test-evidence/2a_B1_2026-11-20
```

**Results.** Fill the results sheet (section 12) as you go: Pass, Fail, or Gap (with the fallback), and a one-line note.

## 4. Order of the day

The checks are grouped to need only one long power-off:

1. **Phase 1:** B1, B2 (about 10 minutes). Tells you the CPU and Python, needed for the `cryptography` wheel.
2. **Phase 2:** A1 to A10 (1.5 to 2 hours). The go/no-go.
3. **Phase 3:** B3, B5, B6, B7 setup, C4, C1, D1, D2, E1, F1 to F6, G1, G2 (about 1 hour).
4. **Phase 4:** one 10-minute power-off for C2, C3 and B7 (about 20 minutes).
5. **Phase 5:** B4, when the `cryptography` wheel is ready.

## 5. Phase 1: what is this machine?

### B1. Kernel, OS and CPU (records only)

```sh
B1# { uname -r; uname -m; cat /etc/os-release; } 2>&1 | tee /root/2a/B1.txt
```

**Record:** the kernel version, the architecture (`uname -m`, for example `armv7l` or `aarch64`) and the OS name and version.

### B2. Python (PLT-6, DC-1)

```sh
B1# { python3 --version; python3 -m pip --version; } 2>&1 | tee /root/2a/B2.txt
```

**Pass:** Python 3.9 or later. Note the exact version: if it is not 3.9, the developers change the version the project targets (through a DC entry).
**If there is no Python, or no pip:** record it. Fallback: the release ships its own Python runtime.

## 6. Phase 2: CAN, the go/no-go

### A1. SocketCAN interfaces (PLT-1, SC-6) — go/no-go

```sh
B1# { ip link show; ip -details link show can0; } 2>&1 | tee /root/2a/A1.txt
```

**Pass:** `ip link show` lists one or more interfaces of type `can` (named like `can0`), and `ip -details` shows a CAN driver and its bit-timing limits.
**Record:** every CAN interface name, and which one is wired to the bus.
**If no CAN interface exists:** **no-go**. Stop and record.

### A2. Who owns the CAN channels

DG's own software may hold the channels. Find out, and free them.

```sh
B1# { systemctl list-units --type=service --state=running; ps aux; } 2>&1 | tee /root/2a/A2_services.txt
```

Look for DG services (names mentioning DG, Beacon, CAN, telematics or similar). Stop each one (`systemctl stop <name>`) and list them in the results. Then check that you can read the bus. On Beacon 2, make some traffic:

```sh
B2# ip link set can0 down; ip link set can0 type can bitrate 250000; ip link set can0 up
B2# cangen can0 -g 100
```

On Beacon 1 (with the interface up at 250 kbit/s in normal mode, as above):

```sh
B1# timeout 10 candump can0 2>&1 | tee /root/2a/A2_candump.txt
```

**Pass:** `candump` shows Beacon 2's frames once the DG services are stopped.
**Record:** the services you had to stop. `install.sh` will disable them. Stop `cangen` on Beacon 2 (Ctrl-C).

### A3. Listen-only mode (NP-1, PLT-2) — go/no-go

The key safety check: in listen-only mode, Beacon 1 must not even acknowledge frames. The test uses that: if Beacon 1 is the only other node and does not acknowledge, Beacon 2's frames go unacknowledged and Beacon 2 reports errors.

1. Make sure **Beacon 1 and Beacon 2 are the only nodes on the bus.** On a full rig, disconnect the rig ECUs for this check.
2. Put Beacon 1 in listen-only mode:
   ```sh
   B1# ip link set can0 down
   B1# ip link set can0 type can bitrate 250000 listen-only on
   B1# ip link set can0 up
   B1# ip -details link show can0 2>&1 | tee /root/2a/A3_mode.txt
   ```
   The output must include `LISTEN-ONLY`.
3. Start recording on Beacon 1: `B1# timeout 15 candump can0 2>&1 | tee /root/2a/A3_candump.txt &`
4. On Beacon 2, send for a few seconds, then look at its error counters:
   ```sh
   B2# cangen can0 -g 100 -n 20
   B2# ip -details -statistics link show can0 2>&1 | tee /root/2a/A3_beacon2.txt
   ```

**Pass, all three:** `LISTEN-ONLY` is shown on Beacon 1; Beacon 1's `candump` shows the frames; Beacon 2's statistics show errors: its `state` is `ERROR-PASSIVE` or `ERROR-WARNING` and its `berr-counter tx` is above zero, because nobody acknowledged its frames.
**If Beacon 2 shows no errors** while Beacon 1 is the only other node, Beacon 1 acknowledged the frames, so it is not really listen-only: **no-go.**
**If `listen-only on` is refused** by `ip link`: **no-go.**

Afterwards, reset Beacon 2 (its error state stays until the interface is restarted):

```sh
B2# ip link set can0 down; ip link set can0 up
```

### A4. Normal mode and transmit (NP-2, SC-6) — go/no-go

```sh
B1# ip link set can0 down
B1# ip link set can0 type can bitrate 250000 listen-only off
B1# ip link set can0 up
B2# timeout 10 candump can0 2>&1 | tee /root/2a/A4_beacon2.txt &
B1# cansend can0 18EAFF00#00EE00
B1# ip -details -statistics link show can0 2>&1 | tee /root/2a/A4_beacon1.txt
```

`18EAFF00#00EE00` is a Request for Address Claim (PGN 59904 asking for 60928), one of the frames the logger is allowed to send.
**Pass:** Beacon 2's `candump` shows `18EAFF00 [3] 00 EE 00`, and Beacon 1 reports no transmit errors.
**If the frame does not appear:** **no-go.**

### A5. Both bit rates (SC-2)

Repeat A3 and A4 with `bitrate 500000` on **both** Beacons (save as `A5_*.txt`). Afterwards set both back to 250000.
**Pass:** both work at 500 kbit/s.

### A6. Error frames and error-passive flags (NP-3, PLT-2)

The logger turns transmit off on bus-off or error-passive (NP-3), which needs the controller to report them.

```sh
B1# ip link set can0 down
B1# ip link set can0 type can bitrate 250000 berr-reporting on
B1# ip link set can0 up
B1# timeout 30 candump -e can0,0~0,#FFFFFFFF 2>&1 | tee /root/2a/A6.txt &
B1# cangen can0 -g 50 -n 100
```

While `cangen` runs, **on the rig only**, disconnect Beacon 2 from the bus, so nothing acknowledges Beacon 1's frames, or briefly short CAN-H to CAN-L.
**Pass:** error frames appear, and their decoded text shows the controller state, `error-passive` and, if forced long enough, `bus-off`.
**If no error frames appear:** record it as a gap. Fallback: the logger relies on transmit errors (`ENOBUFS`) alone.

Reconnect Beacon 2 afterwards.

### A7. The controller stays bus-off (`restart-ms 0`, NP-3)

```sh
B1# ip link set can0 down
B1# ip link set can0 type can bitrate 250000 restart-ms 0
B1# ip link set can0 up
```

Force a bus-off as in A6 (send with Beacon 2 disconnected until errors stop the controller), reconnect Beacon 2, wait 10 seconds, then:

```sh
B1# ip -details link show can0 2>&1 | tee /root/2a/A7.txt
```

**Pass:** `restart-ms 0` is shown, and the state is still `BUS-OFF`: the controller did not restart itself. Bring it back with `ip link set can0 down; ip link set can0 up`.

### A8. Termination can be off (HW-2, PLT-2)

```sh
B1# ip -details link show can0 2>&1 | tee /root/2a/A8_before.txt
B1# ip link set can0 down
B1# ip link set can0 type can bitrate 250000 termination 0
B1# ip link set can0 up
B1# ip -details link show can0 2>&1 | tee /root/2a/A8_after.txt
```

**Pass:** either the output lists `termination 0` (and the values the controller supports), or the controller has no switchable termination, which also passes if the hardware has none fitted (check with DG or the datasheet).
**Record:** which of the two.
**If termination is on and cannot be turned off:** record it. The tap then must not be used on a vehicle; ask DG.

### A9. Kernel timestamps and drop count (LOG-15, PLT-2)

```sh
B2# cangen can0 -g 0 -n 20000 &
B1# timeout 10 candump -td -d can0 2>&1 | tail -40 | tee /root/2a/A9.txt
```

**Pass:** each line starts with a time difference (kernel timestamps work), and `candump` did not print "SO_RXQ_OVFL not supported". Lines starting `DROPCOUNT` show dropped frames, if any were dropped; they are not required.

### A10. Receive buffer can be raised (LOG-15)

```sh
B1# { sysctl net.core.rmem_max; sysctl -w net.core.rmem_max=4194304; sysctl net.core.rmem_max; } 2>&1 | tee /root/2a/A10.txt
```

**Pass:** the last line reads `4194304`. The logger's default buffer is 1 MiB (`can.rx_buffer_bytes`).

**End of phase 2.** If A1, A3 and A4 passed, the Beacon is a **go**. Write it on the results sheet.

## 7. Phase 3: software, storage, light, security

### B3. Offline install of the logger (PLT-6)

Disconnect any network except the laptop link, plug in the USB stick, and find where it mounted (`lsblk`, `findmnt`).

```sh
B1# { python3 -m venv /root/2a-venv && /root/2a-venv/bin/pip install --no-index --find-links /media/usb/wheels j1939-logger && /root/2a-venv/bin/python -c "import j1939logger; print('ok')"; } 2>&1 | tee /root/2a/B3.txt
```

(Use the stick's real mount point in place of `/media/usb`.) **Pass:** it prints `ok` with no internet. **If `venv` or `pip` is missing:** record it. Fallback: a self-contained Python runtime. Remove `/root/2a-venv` afterwards.

### B5. CPU, memory and space (PLT-7 baseline)

```sh
B1# { nproc; free -m; df -h; } 2>&1 | tee /root/2a/B5.txt
```

Records only. The sizing check is SC-9 in step 8.

### B6. systemd and its watchdog (PLT-8, STS-18)

The logger runs under a systemd watchdog: if it stops reporting, systemd restarts it. This checks that the Beacon's systemd does that.

1. `B1# systemctl --version | tee /root/2a/B6_version.txt`
2. Create `/etc/systemd/system/wdtest.service`:
   ```ini
   [Unit]
   Description=Watchdog test for step 2a (B6)

   [Service]
   Type=notify
   NotifyAccess=all
   ExecStart=/bin/sh -c 'systemd-notify --ready; sleep infinity'
   WatchdogSec=10
   Restart=on-watchdog
   ```
3. Start it and wait:
   ```sh
   B1# systemctl daemon-reload
   B1# systemctl start wdtest
   B1# sleep 25
   B1# journalctl -u wdtest --no-pager 2>&1 | tee /root/2a/B6.txt
   ```

**Pass:** the journal shows a watchdog timeout about 10 seconds after start, and the unit started again.
**Fallback:** a separate supervisor process does the hang check.
Clean up: `systemctl stop wdtest; rm /etc/systemd/system/wdtest.service; systemctl daemon-reload`.

### B7 (setup). A custom service that starts at boot

Create `/etc/systemd/system/boottest.service`:

```ini
[Unit]
Description=Boot test for step 2a (B7)

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'date -u >> /root/2a/B7_boots.txt'

[Install]
WantedBy=multi-user.target
```

```sh
B1# systemctl daemon-reload && systemctl enable boottest
```

It is checked after the power cycle in phase 4.

### C4. Turn time sync off (STS-20)

```sh
B1# systemctl status systemd-timesyncd ntp ntpd chronyd --no-pager 2>&1 | tee /root/2a/C4.txt
```

**Record:** which time services exist and run. Stop and disable each one for the rest of the day (`systemctl disable --now <name>`); `install.sh` will do the same. This must be done before C3.

### C1. A real-time clock exists (HW-7, PLT-3)

```sh
B1# { ls -l /dev/rtc*; hwclock -r; dmesg | grep -i rtc; } 2>&1 | tee /root/2a/C1.txt
```

**Pass:** `/dev/rtc0` exists and `hwclock -r` prints a sensible time.
**If not:** record it. Fallback: a USB or I2C RTC module.

### D1. The card's filesystem and mount point (PLT-5, HW-9)

```sh
B1# { lsblk -f; findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS; } 2>&1 | tee /root/2a/D1.txt
```

**Pass:** the microSD card is ext4.
**Record:** where it is mounted. The laptop tool assumes `/media/card` until this result.

### D2. Writable internal flash for `state.json` (LOG-5)

Find a directory on internal flash (not the card) that stays writable. Candidates are a data partition or `/var`.

```sh
B1# { findmnt; df -h; touch /var/lib/probe-2a && rm /var/lib/probe-2a && echo writable; } 2>&1 | tee /root/2a/D2.txt
```

Try other directories if needed. **Pass:** a writable directory on flash with 100 MB free.
**Record:** its path.
**Fallback:** with no writable flash there is no `state.json`: numbering and the chain continue from the card, and when a new card is fitted `install.sh` asks for the next session number (B-SN1).

### E1. A controllable LED (STS-1, PLT-8)

```sh
B1# ls /sys/class/leds 2>&1 | tee /root/2a/E1.txt
B1# cat /sys/class/leds/<led>/trigger
B1# echo none > /sys/class/leds/<led>/trigger; echo 1 > /sys/class/leds/<led>/brightness
B1# echo timer > /sys/class/leds/<led>/trigger; echo 1000 > /sys/class/leds/<led>/delay_on; echo 1000 > /sys/class/leds/<led>/delay_off
B1# echo 100 > /sys/class/leds/<led>/delay_on; echo 100 > /sys/class/leds/<led>/delay_off
```

**Pass:** one LED can be steady on, blink slowly and blink fast.
**Record:** its name, and whether `timer` is listed as a trigger. Put the LED back as it was (`echo <original> > .../trigger`).
**Fallback:** a USB indicator, or the status file only.

### F1. The laptop link (STS-5)

Connect the laptop to the Beacon's USB-B port, then to its Ethernet port.

```sh
B1# { ip link; ip addr; ls /etc/dnsmasq.conf /usr/sbin/dnsmasq 2>&1; } 2>&1 | tee /root/2a/F1.txt
```

**Pass:** an interface appears for the laptop link (`usb0` or similar for USB; `eth0` for Ethernet), and the laptop can reach the Beacon over it.
**Record:** the interface names, and whether a DHCP server (`dnsmasq`) is installed.

### F2 to F6. Security survey (STS-5, STS-20)

```sh
B1# { ss -tlnp; ss -ulnp; } 2>&1 | tee /root/2a/F2.txt
B1# getent passwd | awk -F: '$7 !~ /nologin|false/' 2>&1 | tee /root/2a/F3.txt
B1# { ip link; rfkill list; lsmod | grep -i -E 'cfg80211|bluetooth|wl'; } 2>&1 | tee /root/2a/F4.txt
B1# sshd -T 2>&1 | grep -i -E 'permitrootlogin|passwordauthentication|exposeauthinfo' | tee /root/2a/F5.txt
B1# findmnt / 2>&1 | tee /root/2a/F6.txt
```

**Record:**

- F2: every listening service. FTP and the web server must be possible to turn off; list what stays.
- F3: accounts with a login shell. Each default account must be removable or lockable.
- F4: radio drivers (Wi-Fi, Bluetooth). Each must be possible to turn off at the driver level.
- F5: `ExposeAuthInfo` must be a known option. The logger uses it to identify the operator's key. If `sshd -T` reports it as unknown, record a gap.
- F6: the root filesystem's mount options. Note whether it can be mounted read-only, and what must stay writable.

### G1, G2. Inspection

- **G1 (HW-4):** from the datasheet, the rated operating temperature. It must cover −40 to +85 °C.
- **G2 (HW-2):** look at the tap and the logger cable. No terminator may be fitted.

Photograph each and save the photos as `docs/test-evidence/HW-4_<date>.jpg` and `HW-2_<date>.jpg`.

## 8. Phase 4: one power-off, three checks (C2, C3, B7)

1. Check that time sync is off (C4) and no network cable is connected.
2. Note the exact time: `B1# date -u | tee /root/2a/C2_before.txt`
3. Shut down cleanly (`poweroff`), then switch the supply off. **Wait 10 minutes.**
4. Switch on. As soon as you can log in:
   ```sh
   B1# { date -u; hwclock -r; dmesg | grep -i -E 'hctosys|rtc'; journalctl -k -b --no-pager | grep -i hctosys; cat /root/2a/B7_boots.txt; } 2>&1 | tee /root/2a/C2_C3_B7.txt
   ```

**Pass:**

- **C2:** the time is about 10 minutes plus the boot time after the time you noted, to within a few seconds. The clock kept time while off.
- **C3:** the kernel log has an `hctosys` line (the kernel set the system clock from the RTC at boot), and `date -u` matches `hwclock -r` (allowing for `hwclock`'s time zone). With no network and time sync off, nothing else could have set the clock.
- **B7:** `B7_boots.txt` has a line written at this boot.

**If C2 or C3 fails:** record it. Fallback: a USB or I2C RTC module.
Clean up B7: `systemctl disable boottest; rm /etc/systemd/system/boottest.service; systemctl daemon-reload`.

## 9. Phase 5: the `cryptography` package (B4)

On the Linux machine, download the wheel for the Beacon's architecture (B1) and Python version (B2), for example:

```sh
python3 -m pip download --only-binary=:all: --platform manylinux2014_aarch64 --python-version 3.9 --implementation cp -d crypto cryptography
```

Copy `crypto/` to the USB stick. Then, with no network:

```sh
B1# { python3 -m venv /root/2a-venv && /root/2a-venv/bin/pip install --no-index --find-links /media/usb/crypto cryptography && /root/2a-venv/bin/python -c "import cryptography; print(cryptography.__version__)"; } 2>&1 | tee /root/2a/B4.txt
```

**Pass:** it prints a version. **Fallback:** a self-contained Python runtime (as for B3).

## 10. Finish

1. Put both Beacons' CAN interfaces back to 250 kbit/s, normal mode, termination off.
2. Copy the evidence folders to the laptop (section 3a; the script does this itself), and add the photos.
3. Fill in the results sheet below, and hand it to the developers with the evidence.

## 11. What the developers do with the results

In one pull request:

1. Write each result into "Open items affecting requirements" in `docs/requirements.md` and the matching rows of `docs/verification.md`. HW-2, HW-4, PLT-1 and PLT-6 have no result yet; PLT-2, PLT-3, PLT-5, PLT-8, STS-1, STS-18, STS-20 and LOG-15 get their Beacon notes.
2. Record the go or no-go, and any switch to the backup platform, in the transition overview and a DC entry.
3. Change code defaults through DC entries where the Beacon differs: the Python version (B2), `can.interface` (A1), the card mount (D1), the flash path (D2), and the services, radios and accounts `install.sh` must turn off (A2, C4, F2 to F4).
4. Fill the "2a. Beacon go/no-go" row in `docs/reviews.md` with the name of the person who ran it.

Step 2a is done when every check has a result or a recorded gap, and the go or no-go decision is recorded.

## 12. Results sheet

Date: ____________ Run by: ____________ Observer (optional): ____________
Beacon 1 serial and software version: ____________ Beacon 2: ____________ Bit rate: ____________

| Check | Result (Pass / Fail / Gap) | Note (values, names, fallback chosen) |
| --- | --- | --- |
| B1 Kernel, OS, CPU | | |
| B2 Python | | |
| A1 SocketCAN (go/no-go) | | |
| A2 Channel owners | | |
| A3 Listen-only (go/no-go) | | |
| A4 Transmit (go/no-go) | | |
| A5 500 kbit/s | | |
| A6 Error frames | | |
| A7 Stays bus-off | | |
| A8 Termination off | | |
| A9 Timestamps, drop count | | |
| A10 Receive buffer | | |
| B3 Offline install | | |
| B4 cryptography | | |
| B5 CPU, RAM, space | | |
| B6 Watchdog | | |
| B7 Boot service | | |
| C1 RTC present | | |
| C2 Time across power-off | | |
| C3 Boot clock (hctosys) | | |
| C4 Time sync services | | |
| D1 Card filesystem, mount | | |
| D2 Writable flash | | |
| E1 LED | | |
| F1 Laptop link | | |
| F2 Listening services | | |
| F3 Accounts | | |
| F4 Radios | | |
| F5 SSH options | | |
| F6 Read-only root | | |
| G1 Temperature range | | |
| G2 No terminator on tap | | |
| **Decision** | **Go / No-go** | |
