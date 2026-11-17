# Step 2a run sheet: Beacon go/no-go

For the bench day of build step 2a (decisions X18, X41). It turns the "Beacon go/no-go checks" open item in `docs/requirements.md` into commands to run and results to write down. No logger code runs; nothing here transmits on a vehicle.

## Before you start

- **Where:** on the rig, not a truck. Beacon 1 is the unit under test; Beacon 2 (or any SocketCAN node with can-utils) is the second node and traffic source.
- **Bus:** the rig bus terminated at both ends (120 Ω). The logger adds no termination of its own (HW-2), so the rig must supply it.
- **People:** Vaughan Lynn or Elijah Umaru; one person is enough (2026-11-17). If a second person is there, they observe and their name goes on the results too.
- **Kit:** a laptop with Ethernet and the USB cable for the Beacon's USB-B port, a bench supply you can switch off, the Beacon's datasheet, a card of the planned type, and a USB stick with the release wheels for the offline install test (B3).
- **Evidence:** save each command's output as `docs/test-evidence/<ID>_<date>.txt` (for example `PLT-1_2026-11-20.txt`), as `bench/checklists.md` asks.
- **Shell:** run as root where marked `#`; `can0` stands for whichever interface `ip link show` lists.

## The go/no-go rule

| If this fails | Then |
| --- | --- |
| A1 SocketCAN, A4 transmit, or A3 listen-only | **No-go for the Beacon.** Switch the hardware tier to the backup platform (X21, `docs/porting.md`). The vcan fallback (X12) applies only if the backup also fails |
| Anything else | Go, with the fallback in the last column of the tables below, recorded as a gap |

## A. CAN (go/no-go)

| # | Check | Command | Record | Pass |
| --- | --- | --- | --- | --- |
| A1 | SocketCAN interfaces exist (PLT-1, SC-6) | `ip link show`; `ip -details link show can0` | Interface names and driver | At least one `can` interface with a SocketCAN driver. Note the name for `can.interface` (config default `can0`) |
| A2 | Who owns the CAN channels | `systemctl list-units --type=service --state=running`; `fuser -v /dev/can* 2>/dev/null`; stop the DG services, then `candump can0` | DG services that hold the channel | `candump` sees rig traffic once DG services are stopped. List the services to disable in `install.sh` |
| A3 | Listen-only mode (NP-1, PLT-2) | `# ip link set can0 down`; `# ip link set can0 type can bitrate 250000 listen-only on`; `# ip link set can0 up`; `ip -details link show can0`. On Beacon 2: `cangen can0 -g 100` with Beacon 1 the only other node | Whether `LISTEN-ONLY` shows; Beacon 2's error counters | `LISTEN-ONLY` is shown, Beacon 1 receives the frames, **and** Beacon 2 gets no acknowledgement (its error counters rise). That proves Beacon 1 does not ACK |
| A4 | Normal mode and transmit (NP-2, SC-6) | Bring `can0` up without `listen-only`; `cansend can0 18EAFF00#00EE00` (a Request for Address Claim) | Whether Beacon 2's `candump` sees the frame | Frame seen on Beacon 2, no errors |
| A5 | Bit rates (SC-2) | Repeat A3 and A4 at `bitrate 500000` | Both rates | Both work |
| A6 | Error frames and error-passive flags (NP-3, PLT-2) | `# ip link set can0 down`; `# ip link set can0 type can bitrate 250000 berr-reporting on`; `# ip link set can0 up`; `candump -e can0,0~0,#FFFFFFFF`; on the rig only: disconnect the other node, or briefly short CAN-H to CAN-L | Error frames with controller state | Error frames arrive and show TX/RX error-passive (and bus-off when forced) |
| A7 | `restart-ms 0` honoured (NP-3) | `# ip link set can0 down`; `# ip link set can0 type can bitrate 250000 restart-ms 0`; `# ip link set can0 up`; force a bus-off as in A6, then `ip -details link show can0` | Whether the controller stays bus-off | `restart-ms 0` shown; no automatic restart |
| A8 | Termination switchable off (HW-2, PLT-2) | `ip -details link show can0` (look for `termination`); `# ip link set can0 type can termination 0` | Supported values | Termination can be off, or the hardware has none. Record which |
| A9 | Kernel timestamps and drop count (LOG-15, PLT-2) | `candump -td -d can0` while Beacon 2 runs `cangen can0 -g 0` | Timestamps present; whether the `DROPCOUNT` (SO_RXQ_OVFL) line appears | Both present |
| A10 | Receive buffer can be raised (LOG-15) | `sysctl net.core.rmem_max`; `# sysctl -w net.core.rmem_max=4194304`; `sysctl net.core.rmem_max` | Before and after | Raised value reads back, as root or with CAP_NET_ADMIN. Config default `can.rx_buffer_bytes` is 1 MiB |

## B. System and software

| # | Check | Command | Record | Pass / fallback |
| --- | --- | --- | --- | --- |
| B1 | Kernel and OS | `uname -r`; `uname -m`; `cat /etc/os-release` | Versions, architecture | Recorded |
| B2 | Python (PLT-6, DC-1) | `python3 --version`; `python3 -m pip --version` | Version | 3.9 or later passes. If it differs from 3.9, the developers raise DC-1's floor in `pyproject.toml` and CI with a DC entry. Fallback: a self-contained Python runtime |
| B3 | Offline install (PLT-6) | Disconnect the network; `python3 -m pip install --no-index --find-links /media/usb/wheels <package>` | Result | Installs without internet. Fallback: self-contained runtime |
| B4 | cryptography package (open item, LOG-24 later) | Same as B3 with the `cryptography` wheel | Result | Installs. Fallback: self-contained runtime |
| B5 | CPU, RAM, space (PLT-7 baseline) | `nproc`; `free -m`; `df -h` | Figures | Recorded; the sizing check is SC-9 in step 8 |
| B6 | systemd and watchdog (PLT-8, STS-18) | `systemctl --version`; install the test unit below (it reports ready, then never pings the watchdog); `# systemctl start wdtest`; wait 15 s; `journalctl -u wdtest` | Version; the journal lines | The journal shows a watchdog timeout after `WatchdogSec` (10 s) and the unit restarted. Fallback: a separate supervisor process |
| B7 | A custom service starts at boot (deployment) | Install and `systemctl enable` a test unit that writes a line to a file; power-cycle | Whether the line appears | It does |

The B6 test unit, `/etc/systemd/system/wdtest.service` (remove it after the check):

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

`systemd-notify --ready` sends READY=1; the unit then never sends WATCHDOG=1, so systemd should kill and restart it after 10 s. Run `systemctl daemon-reload` after creating the file.

## C. Clock (HW-7, PLT-3, LOG-16)

| # | Check | Command | Record | Pass / fallback |
| --- | --- | --- | --- | --- |
| C1 | An RTC exists | `ls /dev/rtc*`; `hwclock -r`; `dmesg \| grep -i rtc` | Device, reading | Present. Fallback: a USB or I2C RTC module |
| C2 | It keeps time across power loss | Note `date -u`, power off for 10 minutes with no network, power on, `hwclock -r` | Drift over the gap | Within a few seconds |
| C3 | Boot clock (`hctosys`) | With NTP off (C4) and no network: power-cycle, then at once `dmesg \| grep -i hctosys` (or `journalctl -k -b \| grep -i hctosys`); `date -u`; `hwclock -r` | The `hctosys` line; both readings | The kernel log shows `hctosys` setting the system clock from the RTC, and `date -u` matches `hwclock -r` (allowing for its time zone) to within a few seconds. With no network and NTP off, nothing else could have set it |
| C4 | NTP off (STS-20) | `systemctl status systemd-timesyncd ntp chronyd 2>/dev/null` | Which run | List what `install.sh` must disable |

## D. Storage (PLT-5, HW-9, LOG-5, LOG-22)

| # | Check | Command | Record | Pass / fallback |
| --- | --- | --- | --- | --- |
| D1 | Card filesystem and mount | `lsblk -f`; `findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS` | Filesystem, mount point | ext4. Note the mount point: `j1939ctl` assumes `/media/card` (`--card`) until this result |
| D2 | Writable internal flash for `state.json` | `findmnt` for the root and data partitions; `touch <dir>/probe && rm <dir>/probe`; `df -h <dir>` | A writable directory with 100 MB free | Present. Fallback: with no writable flash there is no `state.json` (LOG-5): numbering and the chain continue from the card, and when a new card is fitted `install.sh` asks for the next session number (B-SN1) |

## E. Status light (STS-1, PLT-8)

| # | Check | Command | Record | Pass / fallback |
| --- | --- | --- | --- | --- |
| E1 | Controllable LEDs | `ls /sys/class/leds`; `# echo 1 > /sys/class/leds/<led>/brightness`; `# echo timer > /sys/class/leds/<led>/trigger` | LED names; whether steady and blink work | One LED can show steady, slow and fast blink. Fallback: a USB indicator, or the status file only |

## F. Network and security survey (STS-5, STS-20)

| # | Check | Command | Record | Pass / fallback |
| --- | --- | --- | --- | --- |
| F1 | USB-Ethernet on the USB-B port | Connect the laptop; `ip link`; `ip addr` on both ends | Interface name (`usb0` or similar) | A wired link the laptop can reach. Note whether a DHCP server (`dnsmasq`) is available |
| F2 | Listening services | `ss -tlnp`; `ss -ulnp` | Every listener | FTP and the web server can be turned off; list what stays |
| F3 | Accounts | `getent passwd \| awk -F: '$7 !~ /nologin\|false/'` | Accounts with a shell | Each default account can be removed or locked |
| F4 | Radios | `ip link`; `rfkill list`; `lsmod \| grep -i -E 'cfg80211\|bluetooth\|wl'` | Radio drivers | Each can be turned off at the driver level |
| F5 | SSH options | `sshd -T \| grep -i -E 'permitrootlogin\|passwordauthentication\|exposeauthinfo'` | Values | `ExposeAuthInfo` is supported (STS-5 needs it to identify the operator) |
| F6 | Read-only root (STS-20) | `findmnt /` | Mount options | Can be mounted read-only; note what needs to stay writable |

## G. Inspection items

| # | Check | How | Record |
| --- | --- | --- | --- |
| G1 | Operating temperature (HW-4) | The Beacon datasheet | The rated range; it must cover −40 to +85 °C |
| G2 | Termination on the tap (HW-2) | Look at the tap and the logger cable | No terminator fitted |

## After the run

The developers, in one pull request:

1. Write each result into the "Open items affecting requirements" table in `docs/requirements.md` and the matching rows of `docs/verification.md` (HW-2, HW-4, PLT-1 and PLT-6 have no result yet; PLT-2, PLT-3, PLT-5, PLT-8, STS-1, STS-18, STS-20 and LOG-15 get their Beacon notes).
2. Record the go or no-go decision, and any switch to the backup platform, in the transition overview and a DC entry.
3. Change code defaults only through a DC entry where they depart from a contract: the Python floor (B2), `can.interface` (A1), the card mount (D1), the flash path (D2), and the services and radios `install.sh` must disable (A2, C4, F2 to F4).
4. Fill the "2a. Beacon go/no-go" row in `docs/reviews.md` with the observer's name.
5. Step 2a is done when every check above has a result or a recorded gap, and the go or no-go decision is recorded.
