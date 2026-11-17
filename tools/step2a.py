#!/usr/bin/env python3
"""step2a: run the step 2a Beacon go/no-go checks from the laptop (DC-29).

Runs the checks in ``docs/step-2a-procedure.md`` on Beacon 1 (the unit under
test) and Beacon 2 (the second node) over SSH, saves each check's output as
evidence, suggests a result where a machine can judge it, prompts the operator
for the physical steps, and writes the procedure's results sheet pre-filled for
the operator to confirm. Standard library only; nothing is installed on the
Beacons. The procedure stays the reference: every check can still be run by hand.

    python tools/step2a.py --beacon1 root@<b1> --beacon2 root@<b2> --wheels wheels/
    python tools/step2a.py ... --resume docs/test-evidence/2a_2026-11-20   # after the power-off

Exit codes: 0 done (go), 1 no-go, 2 usage, 3 stopped by the operator.
Safety: the only frames sent are the procedure's own (``cangen`` from Beacon 2,
one Request for Address Claim from Beacon 1 in A4), and only after the
operator confirms the setup is the bench, not a vehicle.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Protocol

ROOT = Path(__file__).resolve().parents[1]
B1, B2 = "beacon1", "beacon2"
GO_NO_GO = ("A1", "A3", "A4")

# The procedure's results sheet (docs/step-2a-procedure.md, section 12), in its order.
SHEET: tuple[tuple[str, str], ...] = (
    ("B1", "B1 Kernel, OS, CPU"),
    ("B2", "B2 Python"),
    ("A1", "A1 SocketCAN (go/no-go)"),
    ("A2", "A2 Channel owners"),
    ("A3", "A3 Listen-only (go/no-go)"),
    ("A4", "A4 Transmit (go/no-go)"),
    ("A5", "A5 500 kbit/s"),
    ("A6", "A6 Error frames"),
    ("A7", "A7 Stays bus-off"),
    ("A8", "A8 Termination off"),
    ("A9", "A9 Timestamps, drop count"),
    ("A10", "A10 Receive buffer"),
    ("B3", "B3 Offline install"),
    ("B4", "B4 cryptography"),
    ("B5", "B5 CPU, RAM, space"),
    ("B6", "B6 Watchdog"),
    ("B7", "B7 Boot service"),
    ("C1", "C1 RTC present"),
    ("C2", "C2 Time across power-off"),
    ("C3", "C3 Boot clock (hctosys)"),
    ("C4", "C4 Time sync services"),
    ("D1", "D1 Card filesystem, mount"),
    ("D2", "D2 Writable flash"),
    ("E1", "E1 LED"),
    ("F1", "F1 Laptop link"),
    ("F2", "F2 Listening services"),
    ("F3", "F3 Accounts"),
    ("F4", "F4 Radios"),
    ("F5", "F5 SSH options"),
    ("F6", "F6 Read-only root"),
    ("G1", "G1 Temperature range"),
    ("G2", "G2 No terminator on tap"),
)

WDTEST = """[Unit]
Description=Watchdog test for step 2a (B6)

[Service]
Type=notify
NotifyAccess=all
ExecStart=/bin/sh -c 'systemd-notify --ready; sleep infinity'
WatchdogSec=10
Restart=on-watchdog
"""
BOOTTEST = """[Unit]
Description=Boot test for step 2a (B7)

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'date -u +%s >> /root/2a-boots.txt'

[Install]
WantedBy=multi-user.target
"""
TIME_SERVICES = ("systemd-timesyncd", "ntp", "ntpd", "chronyd")
FLASH_CANDIDATES = ("/var/lib", "/data", "/opt", "/home", "/root")


# -- talking to the Beacons -------------------------------------------------------------


class Pending(Protocol):
    def wait(self, timeout: float) -> tuple[int, str]: ...


class Runner(Protocol):
    """Runs shell commands on a Beacon (``beacon1`` or ``beacon2``)."""

    def run(
        self, role: str, command: str, timeout: float = 120.0, stdin: Optional[str] = None
    ) -> tuple[int, str]: ...

    def spawn(self, role: str, command: str) -> Pending: ...

    def copy(self, role: str, local_dir: Path, remote_dir: str) -> tuple[int, str]: ...


class _Proc:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc

    def wait(self, timeout: float) -> tuple[int, str]:
        try:
            out, _ = self._proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            out, _ = self._proc.communicate()
        return self._proc.returncode, out or ""


class SshRunner:
    """The real runner: the system OpenSSH client, as ``j1939ctl`` uses (DC-21)."""

    def __init__(self, hosts: dict[str, str]) -> None:
        self._hosts = dict(hosts)  # only the hosts given on the command line

    def _args(self, role: str, command: str) -> list[str]:
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self._hosts[role], command]

    def run(
        self, role: str, command: str, timeout: float = 120.0, stdin: Optional[str] = None
    ) -> tuple[int, str]:
        try:
            p = subprocess.run(
                self._args(role, command),
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout if isinstance(exc.stdout, str) else ""
            return 124, out + "\n[step2a: timed out]"
        return p.returncode, p.stdout + p.stderr

    def spawn(self, role: str, command: str) -> Pending:
        proc = subprocess.Popen(
            self._args(role, command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        return _Proc(proc)

    def copy(self, role: str, local_dir: Path, remote_dir: str) -> tuple[int, str]:
        p = subprocess.run(
            [
                "scp",
                "-r",
                "-o",
                "BatchMode=yes",
                str(local_dir),
                f"{self._hosts[role]}:{remote_dir}",
            ],
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr


# -- pass conditions (pure, tested against recorded output) -------------------------------

Verdict = tuple[str, str]  # (Pass | Fail | Gap | Recorded | Manual, note)


def judge_a1(out: str, can: str) -> Verdict:
    names = re.findall(r"^\d+: (\S+?)[:@].*\n\s+link/can", out, re.M)
    if not names:
        return "Fail", "no CAN interface: no-go"
    if can not in names:
        return "Fail", f"CAN interfaces {', '.join(names)}, but not {can}: rerun with --can"
    return "Pass", f"CAN interfaces: {', '.join(names)}"


def judge_frames_seen(dump: str) -> int:
    """Frames in ``candump`` output (lines like ``can0  18EAFF00   [3]  00 EE 00``)."""
    return len(re.findall(r"^\s*\(?[\d. ]*\)?\s*\w+\s+[0-9A-F]{3,8}\s+\[\d\]", dump, re.M))


def judge_a3(mode: str, b1_dump: str, b2_stats: str) -> Verdict:
    if "LISTEN-ONLY" not in mode:
        return "Fail", "LISTEN-ONLY not shown: no-go"
    if judge_frames_seen(b1_dump) == 0:
        return "Fail", "Beacon 1 received no frames in listen-only mode: no-go"
    state = re.search(r"state (ERROR-ACTIVE|ERROR-WARNING|ERROR-PASSIVE|BUS-OFF)", b2_stats)
    tx = re.search(r"berr-counter tx (\d+)", b2_stats)
    if (state and state.group(1) != "ERROR-ACTIVE") or (tx and int(tx.group(1)) > 0):
        found = state.group(1) if state else "errors"
        count = tx.group(1) if tx else "?"
        return "Pass", f"Beacon 1 stayed silent: Beacon 2 went {found} (tx errors {count})"
    return (
        "Fail",
        "Beacon 2 saw no errors: Beacon 1 acknowledged frames, so it is not listen-only: no-go",
    )


def judge_a4(b2_dump: str) -> Verdict:
    if re.search(r"18EAFF00\s+\[3\]\s+00 EE 00", b2_dump.upper()):
        return "Pass", "Beacon 2 saw the Request for Address Claim"
    return "Fail", "Beacon 2 did not see Beacon 1's frame: no-go"


def judge_a6(dump: str) -> Verdict:
    low = dump.lower()
    if "error" not in low:
        return "Gap", "no error frames: the logger relies on transmit errors (ENOBUFS) alone"
    if "passive" in low or "bus-off" in low or "bus off" in low:
        return "Pass", "error frames with error-passive / bus-off"
    return "Gap", "error frames, but no error-passive or bus-off seen"


def judge_a7(details: str) -> Verdict:
    if "restart-ms 0" not in details:
        return "Fail", "restart-ms 0 not shown"
    if "BUS-OFF" in details:
        return "Pass", "stayed bus-off with restart-ms 0"
    return "Gap", "bus-off was not reached; force it longer and rerun --only A7"


def judge_a8(before: str, after: str, rc: int) -> Verdict:
    if rc == 0 and re.search(r"\btermination 0\b", after):
        return "Pass", "termination switched off"
    if "termination" not in before and "termination" not in after:
        return "Gap", "no switchable termination: confirm with DG that none is fitted"
    return "Fail", "termination could not be switched off: do not use the tap on a vehicle; ask DG"


def judge_a9(dump: str) -> Verdict:
    if "SO_RXQ_OVFL not supported" in dump:
        return "Fail", "no drop count (SO_RXQ_OVFL)"
    if re.search(r"^\s*\(\d+\.\d+\)", dump, re.M):
        drops = "DROPCOUNT" in dump
        return "Pass", "kernel timestamps; drop count supported" + ("; drops seen" if drops else "")
    return "Fail", "no timestamps in candump -td output"


def judge_a10(out: str) -> Verdict:
    values = re.findall(r"net\.core\.rmem_max = (\d+)", out)
    if values and values[-1] == "4194304":
        return "Pass", f"raised from {values[0]} to 4194304"
    return "Fail", "rmem_max could not be raised"


def judge_b2(out: str) -> Verdict:
    m = re.search(r"Python (\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        return "Gap", "no Python: fallback is a self-contained runtime"
    major, minor = int(m.group(1)), int(m.group(2))
    version = ".".join(x for x in m.groups() if x)
    if (major, minor) < (3, 9):
        return "Gap", f"Python {version} is older than 3.9: self-contained runtime"
    pip = "pip" in out and "No module named pip" not in out
    note = f"Python {version}" + ("" if (major, minor) == (3, 9) else ": not 3.9, needs a DC")
    return "Pass", note + ("" if pip else "; no pip")


def judge_b6(journal: str) -> Verdict:
    low = journal.lower()
    if "watchdog timeout" in low and ("scheduled restart" in low or low.count("started") >= 2):
        return "Pass", "watchdog timeout, then restarted"
    return "Gap", "no watchdog restart: fallback is a separate supervisor process"


def judge_c1(out: str) -> Verdict:
    return ("Pass", "/dev/rtc0 present") if "rtc0" in out else ("Gap", "no RTC: add a module")


def judge_c2(beacon_elapsed: float, laptop_elapsed: float) -> Verdict:
    drift = beacon_elapsed - laptop_elapsed
    if abs(drift) <= 5.0:
        return "Pass", f"kept time over {laptop_elapsed:.0f} s (drift {drift:+.1f} s)"
    return "Fail", f"drift {drift:+.1f} s over {laptop_elapsed:.0f} s: add an RTC module"


def parse_hwclock(text: str) -> Optional[dt.datetime]:
    m = re.search(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2}:?\d{2})?", text)
    if not m:
        return None
    zone = m.group(3) or "+00:00"
    if ":" not in zone:
        zone = zone[:3] + ":" + zone[3:]
    return dt.datetime.fromisoformat(m.group(1).replace(" ", "T") + zone)


def judge_c3(kernel: str, date_epoch: float, hwclock: str) -> Verdict:
    if "hctosys" not in kernel.lower():
        return "Fail", "no hctosys line: the kernel did not set the clock from the RTC"
    hw = parse_hwclock(hwclock)
    if hw is None:
        return (
            "Manual",
            "hctosys seen; compare date -u and hwclock -r by hand (format not recognised)",
        )
    diff = date_epoch - hw.timestamp()
    if abs(diff) <= 5.0:
        return "Pass", f"hctosys set the clock; date and RTC agree ({diff:+.1f} s)"
    return "Fail", f"date and RTC differ by {diff:+.1f} s"


def card_device(findmnt: str) -> Optional[str]:
    """The microSD card's mounted ext4 partition (``/dev/mmcblkNpM``), if any."""
    m = re.search(r"(/dev/mmcblk\d+p\d+)\s+ext4", findmnt)
    return m.group(1) if m else None


def judge_d1(lsblk: str, findmnt: str) -> Verdict:
    cards = [line for line in lsblk.splitlines() if "mmcblk" in line and "ext4" in line]
    if not cards:
        return "Fail", "no ext4 partition on the microSD card"
    dev = card_device(findmnt)
    where = "not mounted"
    for line in findmnt.splitlines():
        if dev and dev in line:
            where = line.split()[0].lstrip("│├└─ ")
    return "Pass", f"ext4 ({dev or 'device not found'}); mounted at {where} (j1939ctl: /media/card)"


def judge_f5(out: str) -> Verdict:
    if "exposeauthinfo" in out.lower():
        return "Pass", "ExposeAuthInfo supported"
    return "Gap", "ExposeAuthInfo unknown to sshd: operator identity needs another way"


# -- the run ------------------------------------------------------------------------------


@dataclass
class Result:
    verdict: str
    note: str


class Stopped(Exception):
    """The operator stopped the run (exit 3)."""


class Step2a:
    def __init__(
        self,
        runner: Runner,
        evidence: Path,
        *,
        can: str = "can0",
        wheels: Optional[Path] = None,
        crypto: Optional[Path] = None,
        ask: Callable[[str], str] = input,
        say: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.r = runner
        self.dir = evidence
        self.can = can
        self.wheels, self.crypto = wheels, crypto
        self.ask, self.say, self.sleep, self.now = ask, say, sleep, now
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, object] = {"results": {}}
        if (self.dir / "state.json").exists():
            self.state = json.loads((self.dir / "state.json").read_text("utf-8"))

    # -- bookkeeping ----------------------------------------------------------------------

    @property
    def results(self) -> dict[str, dict[str, str]]:
        return self.state["results"]  # type: ignore[return-value]

    def _save_state(self) -> None:
        (self.dir / "state.json").write_text(json.dumps(self.state, indent=2), "utf-8")

    def record(self, check: str, verdict: Verdict) -> None:
        self.results[check] = asdict(Result(*verdict))
        self._save_state()
        self.say(f"{check}: {verdict[0]} - {verdict[1]}")

    def sh(
        self,
        role: str,
        check: str,
        command: str,
        timeout: float = 120.0,
        stdin: Optional[str] = None,
    ) -> tuple[int, str]:
        rc, out = self.r.run(role, command, timeout, stdin)
        tag = "B1" if role == B1 else "B2"
        with (self.dir / f"{check}.txt").open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"[{tag}]$ {command}\n{out}\n[exit {rc}]\n\n")
        return rc, out

    def yes(self, question: str) -> bool:
        return self.ask(question + " [y/n] ").strip().lower().startswith("y")

    def set_can(self, role: str, check: str, extra: str) -> tuple[int, str]:
        c = self.can
        return self.sh(
            role,
            check,
            f"ip link set {c} down; ip link set {c} type can {extra}; ip link set {c} up",
        )

    def todo(self, check: str) -> bool:
        return check not in self.results

    # -- the whole run --------------------------------------------------------------------

    def run(self) -> int:
        try:
            for check in ("B1", "B2", "A1"):
                if self.todo(check):
                    getattr(self, "check_" + check.lower())()
            if self.no_go():
                return self.finish()
            if not self.state.get("bench_confirmed"):
                answer = self.ask(
                    "Type BENCH to confirm Beacons 1 and 2 are on the bench rig, "
                    "not a vehicle (frames will be sent): "
                )
                if answer.strip().upper() != "BENCH":
                    raise Stopped("not confirmed as the bench: nothing was sent")
                self.state["bench_confirmed"] = True
                self._save_state()
            for check in ("A2", "A3", "A4"):
                if self.todo(check):
                    getattr(self, "check_" + check.lower())()
                if self.no_go():
                    return self.finish()
            for check in (
                "A5",
                "A6",
                "A7",
                "A8",
                "A9",
                "A10",
                "B3",
                "B5",
                "B6",
                "C4",
                "C1",
                "D1",
                "D2",
                "E1",
                "F1",
                "F2",
                "F3",
                "F4",
                "F5",
                "F6",
                "G1",
                "G2",
            ):
                if self.todo(check):
                    getattr(self, "check_" + check.lower())()
            if self.todo("C2"):
                self.power_off_checks()
            if self.todo("B4"):
                self.check_b4()
            return self.finish(done=True)
        except (Stopped, KeyboardInterrupt) as exc:
            self.say(
                f"Stopped: {exc or 'interrupted'}. Rerun with --resume {self.dir} to continue."
            )
            self.cleanup(final=False)
            self.write_sheet()
            return 3

    def no_go(self) -> bool:
        return any(self.results.get(c, {}).get("verdict") == "Fail" for c in GO_NO_GO)

    def finish(self, done: bool = False) -> int:
        self.cleanup(final=done or self.no_go())
        self.write_sheet()
        if self.no_go():
            self.say(
                "NO-GO: switch the hardware tier to the backup platform (X21, docs/porting.md)."
            )
            return 1
        self.say(f"Done. Confirm or change each suggestion in {self.dir / 'results.md'}.")
        return 0

    def cleanup(self, final: bool) -> None:
        c = self.can
        for role in (B1, B2):
            self.r.run(
                role,
                f"ip link set {c} down; ip link set {c} type can bitrate 250000 "
                f"listen-only off; ip link set {c} type can termination 0 2>/dev/null; "
                f"ip link set {c} up",
            )
        self.r.run(
            B1,
            "systemctl disable --now wdtest 2>/dev/null; "
            "rm -f /etc/systemd/system/wdtest.service; systemctl daemon-reload",
        )
        if final:  # the boot test must survive an interrupted run until the power-off is done
            self.r.run(
                B1,
                "systemctl disable boottest 2>/dev/null; rm -f "
                "/etc/systemd/system/boottest.service /root/2a-boots.txt; "
                "systemctl daemon-reload; rm -rf /root/2a-venv /root/2a-wheels",
            )

    def decision(self) -> str:
        if self.no_go():
            return "No-go"
        if all(self.results.get(c, {}).get("verdict") == "Pass" for c in GO_NO_GO):
            return "Go"
        return "Not decided"

    def write_sheet(self) -> None:
        h = self.state.get("header", {})
        assert isinstance(h, dict)
        lines = [
            "# Step 2a results (suggested by tools/step2a.py: confirm or change each line)",
            "",
            f"Date: {h.get('date', '')}  Run by: {h.get('run_by', '')}  "
            f"Observer (optional): {h.get('observer', '')}",
            f"Beacon 1: {h.get('beacon1', '')}  Beacon 2: {h.get('beacon2', '')}  Bit rate: 250000",
            "",
            "| Check | Result (Pass / Fail / Gap) | Note (values, names, fallback chosen) |",
            "| --- | --- | --- |",
        ]
        for check, label in SHEET:
            r = self.results.get(check, {"verdict": "", "note": "not run"})
            lines.append(f"| {label} | {r['verdict']} | {r['note']} |")
        lines.append(f"| **Decision** | **{self.decision()}** | |")
        (self.dir / "results.md").write_text("\n".join(lines) + "\n", "utf-8")

    # -- phase 1 --------------------------------------------------------------------------

    def check_b1(self) -> None:
        if "header" not in self.state:
            self.state["header"] = {
                "date": dt.date.fromtimestamp(self.now()).isoformat(),
                "run_by": self.ask("Your name: ").strip(),
                "observer": self.ask("Observer (optional, Enter for none): ").strip(),
                "beacon1": self.ask("Beacon 1 serial number: ").strip(),
                "beacon2": self.ask("Beacon 2 serial number: ").strip(),
            }
        _, out = self.sh(B1, "B1", "uname -r; uname -m; cat /etc/os-release")
        arch = out.splitlines()[1] if len(out.splitlines()) > 1 else "?"
        self.record("B1", ("Recorded", f"kernel {out.splitlines()[0] if out else '?'}; {arch}"))

    def check_b2(self) -> None:
        _, out = self.sh(B1, "B2", "python3 --version; python3 -m pip --version")
        self.record("B2", judge_b2(out))

    # -- phase 2: CAN ---------------------------------------------------------------------

    def check_a1(self) -> None:
        _, out = self.sh(B1, "A1", f"ip -details link show; ip -details link show {self.can}")
        self.record("A1", judge_a1(out, self.can))

    def check_a2(self) -> None:
        self.sh(B1, "A2", "systemctl list-units --type=service --state=running --no-pager; ps aux")
        names = self.ask("Names of DG services to stop (comma-separated, Enter for none): ")
        stopped = [n.strip() for n in names.split(",") if n.strip()]
        for service in stopped:
            self.sh(B1, "A2", f"systemctl stop {service}")
        for role in (B1, B2):
            self.set_can(role, "A2", "bitrate 250000 listen-only off")
        dump = self.r.spawn(B1, f"timeout 10 candump {self.can}")
        self.sleep(1.0)
        self.sh(B2, "A2", f"cangen {self.can} -g 100 -n 30")
        rc, out = dump.wait(15.0)
        self._append("A2", B1, f"timeout 10 candump {self.can}", rc, out)
        n = judge_frames_seen(out)
        note = f"services stopped: {', '.join(stopped) or 'none'}; {n} frames seen"
        self.record("A2", ("Pass", note) if n else ("Fail", note + ": the channel is still held"))

    def _append(self, check: str, role: str, command: str, rc: int, out: str) -> None:
        tag = "B1" if role == B1 else "B2"
        with (self.dir / f"{check}.txt").open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"[{tag}]$ {command}\n{out}\n[exit {rc}]\n\n")

    def _listen_only(self, check: str, rate: int) -> Verdict:
        while not self.yes("Are Beacon 1 and Beacon 2 the only nodes on the bus?"):
            self.ask("Disconnect the rig ECUs, then press Enter.")
        self.set_can(B2, check, f"bitrate {rate} listen-only off")
        self.set_can(B1, check, f"bitrate {rate} listen-only on")
        _, mode = self.sh(B1, check, f"ip -details link show {self.can}")
        dump = self.r.spawn(B1, f"timeout 15 candump {self.can}")
        self.sleep(1.0)
        self.sh(B2, check, f"cangen {self.can} -g 100 -n 20")
        _, stats = self.sh(B2, check, f"ip -details -statistics link show {self.can}")
        rc, out = dump.wait(20.0)
        self._append(check, B1, f"timeout 15 candump {self.can}", rc, out)
        self.sh(B2, check, f"ip link set {self.can} down; ip link set {self.can} up")
        return judge_a3(mode, out, stats)

    def _transmit(self, check: str, rate: int) -> Verdict:
        self.set_can(B1, check, f"bitrate {rate} listen-only off")
        dump = self.r.spawn(B2, f"timeout 10 candump {self.can}")
        self.sleep(1.0)
        self.sh(B1, check, f"cansend {self.can} 18EAFF00#00EE00")
        self.sh(B1, check, f"ip -details -statistics link show {self.can}")
        rc, out = dump.wait(15.0)
        self._append(check, B2, f"timeout 10 candump {self.can}", rc, out)
        return judge_a4(out)

    def check_a3(self) -> None:
        self.record("A3", self._listen_only("A3", 250000))

    def check_a4(self) -> None:
        self.record("A4", self._transmit("A4", 250000))

    def check_a5(self) -> None:
        a3 = self._listen_only("A5", 500000)
        a4 = self._transmit("A5", 500000)
        for role in (B1, B2):
            self.set_can(role, "A5", "bitrate 250000 listen-only off")
        ok = a3[0] == "Pass" and a4[0] == "Pass"
        self.record(
            "A5",
            ("Pass", "listen-only and transmit at 500 kbit/s")
            if ok
            else ("Fail", f"at 500 kbit/s: {a3[1]}; {a4[1]}"),
        )

    def check_a6(self) -> None:
        self.set_can(B1, "A6", "bitrate 250000 berr-reporting on")
        dump = self.r.spawn(B1, f"timeout 30 candump -e {self.can},0~0,#FFFFFFFF")
        self.ask(
            "On the rig only: disconnect Beacon 2 from the bus (or get ready to short "
            "CAN-H to CAN-L briefly), then press Enter."
        )
        self.sh(B1, "A6", f"cangen {self.can} -g 50 -n 100", timeout=60.0)
        rc, out = dump.wait(40.0)
        self._append("A6", B1, f"timeout 30 candump -e {self.can},0~0,#FFFFFFFF", rc, out)
        self.ask("Reconnect Beacon 2, then press Enter.")
        self.record("A6", judge_a6(out))

    def check_a7(self) -> None:
        self.set_can(B1, "A7", "bitrate 250000 restart-ms 0")
        self.ask("On the rig only: disconnect Beacon 2 from the bus, then press Enter.")
        self.sh(B1, "A7", f"cangen {self.can} -g 10 -n 500", timeout=60.0)
        self.ask("Reconnect Beacon 2, then press Enter.")
        self.sleep(10.0)
        _, out = self.sh(B1, "A7", f"ip -details link show {self.can}")
        self.sh(B1, "A7", f"ip link set {self.can} down; ip link set {self.can} up")
        self.record("A7", judge_a7(out))

    def check_a8(self) -> None:
        _, before = self.sh(B1, "A8", f"ip -details link show {self.can}")
        rc, _ = self.set_can(B1, "A8", "bitrate 250000 termination 0")
        _, after = self.sh(B1, "A8", f"ip -details link show {self.can}")
        self.record("A8", judge_a8(before, after, rc))

    def check_a9(self) -> None:
        dump = self.r.spawn(B1, f"timeout 10 candump -td -d {self.can} | tail -40")
        self.sleep(1.0)
        self.sh(B2, "A9", f"cangen {self.can} -g 0 -n 20000", timeout=60.0)
        rc, out = dump.wait(20.0)
        self._append("A9", B1, f"timeout 10 candump -td -d {self.can} | tail -40", rc, out)
        self.record("A9", judge_a9(out))

    def check_a10(self) -> None:
        _, out = self.sh(
            B1,
            "A10",
            "sysctl net.core.rmem_max; "
            "sysctl -w net.core.rmem_max=4194304; sysctl net.core.rmem_max",
        )
        self.record("A10", judge_a10(out))

    # -- phase 3 --------------------------------------------------------------------------

    def _offline_install(
        self, check: str, folder: Optional[Path], package: str, probe: str
    ) -> Verdict:
        if folder is None:
            return "Gap", f"not run: no {package} wheel folder given"
        self.sh(B1, check, "rm -rf /root/2a-wheels")
        rc, out = self.r.copy(B1, folder, "/root/2a-wheels")
        self._append(check, B1, f"scp -r {folder} beacon1:/root/2a-wheels", rc, out)
        rc, out = self.sh(
            B1,
            check,
            "python3 -m venv /root/2a-venv && /root/2a-venv/bin/pip install "
            f"--no-index --find-links /root/2a-wheels {package} && "
            f'/root/2a-venv/bin/python -c "{probe}"',
            timeout=600.0,
        )
        self.sh(B1, check, "rm -rf /root/2a-venv /root/2a-wheels")
        if rc == 0 and out.strip():
            return "Pass", f"{package} installed without internet: {out.strip().splitlines()[-1]}"
        return "Gap", f"{package} did not install offline: self-contained runtime"

    def check_b3(self) -> None:
        self.record(
            "B3",
            self._offline_install(
                "B3", self.wheels, "j1939-logger", "import j1939logger; print('ok')"
            ),
        )

    def check_b4(self) -> None:
        self.record(
            "B4",
            self._offline_install(
                "B4",
                self.crypto,
                "cryptography",
                "import cryptography; print(cryptography.__version__)",
            ),
        )

    def check_b5(self) -> None:
        _, out = self.sh(B1, "B5", "nproc; free -m; df -h")
        self.record("B5", ("Recorded", f"{out.splitlines()[0] if out else '?'} cores; see B5.txt"))

    def check_b6(self) -> None:
        self.sh(B1, "B6", "systemctl --version")
        self.sh(B1, "B6", "cat > /etc/systemd/system/wdtest.service", stdin=WDTEST)
        self.sh(B1, "B6", "systemctl daemon-reload; systemctl start wdtest")
        self.sleep(25.0)
        _, journal = self.sh(B1, "B6", "journalctl -u wdtest --no-pager")
        self.sh(
            B1,
            "B6",
            "systemctl disable --now wdtest 2>/dev/null; "
            "rm -f /etc/systemd/system/wdtest.service; systemctl daemon-reload",
        )
        self.record("B6", judge_b6(journal))
        # B7 setup: the boot test service, checked after the power-off.
        self.sh(B1, "B7", "cat > /etc/systemd/system/boottest.service", stdin=BOOTTEST)
        self.sh(B1, "B7", "systemctl daemon-reload; systemctl enable boottest")

    def check_c4(self) -> None:
        running = []
        for name in TIME_SERVICES:
            _, out = self.sh(B1, "C4", f"systemctl status {name} --no-pager 2>&1 | head -5")
            if "active (running)" in out:
                running.append(name)
        if self.yes("Disable the time sync services now (needed for C3)?"):
            for s in TIME_SERVICES:
                self.sh(B1, "C4", f"systemctl disable --now {s} 2>/dev/null")
        self.record(
            "C4",
            (
                "Recorded",
                "running: "
                + (", ".join(running) or "none found")
                + "; install.sh must disable them",
            ),
        )

    def check_c1(self) -> None:
        _, out = self.sh(B1, "C1", "ls -l /dev/rtc*; hwclock -r; dmesg | grep -i rtc")
        self.record("C1", judge_c1(out))

    def check_d1(self) -> None:
        _, lsblk = self.sh(B1, "D1", "lsblk -f")
        _, mounts = self.sh(B1, "D1", "findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS")
        self.state["card_dev"] = card_device(mounts) or ""
        self.record("D1", judge_d1(lsblk, mounts))

    def check_d2(self) -> None:
        self.sh(B1, "D2", "findmnt; df -h")
        for d in FLASH_CANDIDATES:
            rc, out = self.sh(
                B1,
                "D2",
                f"touch {d}/probe-2a && rm {d}/probe-2a && "
                f"findmnt -n -o SOURCE -T {d} && df -Pk {d} | tail -1",
            )
            card = str(self.state.get("card_dev") or "")
            if rc != 0 or (card and card in out):
                continue  # not writable, or on the card rather than internal flash
            fields = out.split()
            free_kb = int(fields[-3]) if len(fields) >= 3 and fields[-3].isdigit() else 0
            if free_kb >= 100 * 1024:
                self.record(
                    "D2", ("Pass", f"{d} is writable on flash with {free_kb // 1024} MB free")
                )
                return
        self.record(
            "D2",
            (
                "Gap",
                "no writable flash with 100 MB free: numbering continues from "
                "the card; install.sh asks on a new card",
            ),
        )

    def check_e1(self) -> None:
        _, out = self.sh(B1, "E1", "ls /sys/class/leds")
        leds = out.split()
        if not leds:
            self.record("E1", ("Gap", "no LEDs: a USB indicator, or the status file only"))
            return
        led = (
            self.ask(f"LEDs: {', '.join(leds)}. Which one to try? [{leds[0]}] ").strip() or leds[0]
        )
        p = f"/sys/class/leds/{led}"
        _, trig = self.sh(B1, "E1", f"cat {p}/trigger")
        chosen = re.search(r"\[(\S+)\]", trig)  # the active trigger is shown in brackets
        original = chosen.group(1) if chosen else "none"
        self.sh(
            B1,
            "E1",
            f"echo timer > {p}/trigger && echo 100 > {p}/delay_on && echo 100 > {p}/delay_off",
        )
        fast = self.yes(f"Is {led} blinking fast?")
        self.sh(B1, "E1", f"echo 1000 > {p}/delay_on && echo 1000 > {p}/delay_off")
        slow = self.yes(f"Is {led} blinking slowly?")
        self.sh(B1, "E1", f"echo none > {p}/trigger && echo 1 > {p}/brightness")
        steady = self.yes(f"Is {led} on steady?")
        self.sh(B1, "E1", f"echo {original} > {p}/trigger")
        ok = fast and slow and steady
        self.record(
            "E1",
            ("Pass", f"{led}: steady, slow and fast blink")
            if ok
            else ("Gap", f"{led} could not show all three: USB indicator or status file"),
        )

    def check_f1(self) -> None:
        self.ask(
            "Connect the laptop to Beacon 1's USB-B port (then its Ethernet port), "
            "then press Enter."
        )
        _, out = self.sh(B1, "F1", "ip link; ip addr; ls /usr/sbin/dnsmasq 2>&1")
        reach = self.yes("Can the laptop reach Beacon 1 over that link (ping or ssh)?")
        dns = "dnsmasq installed" if "No such file" not in out else "no dnsmasq"
        self.record(
            "F1",
            ("Pass", f"laptop link works; {dns}")
            if reach
            else ("Gap", f"no laptop link over USB-B; {dns}"),
        )

    def check_f2(self) -> None:
        self.sh(B1, "F2", "ss -tlnp; ss -ulnp")
        self.record(
            "F2", ("Recorded", "see F2.txt: FTP and web server must be possible to turn off")
        )

    def check_f3(self) -> None:
        _, out = self.sh(B1, "F3", "getent passwd | awk -F: '$7 !~ /nologin|false/'")
        names = [line.split(":")[0] for line in out.splitlines() if ":" in line]
        self.record("F3", ("Recorded", "accounts with a shell: " + (", ".join(names) or "none")))

    def check_f4(self) -> None:
        self.sh(B1, "F4", "ip link; rfkill list; lsmod | grep -i -E 'cfg80211|bluetooth|wl'")
        self.record("F4", ("Recorded", "see F4.txt: each radio must be possible to turn off"))

    def check_f5(self) -> None:
        _, out = self.sh(
            B1, "F5", "sshd -T | grep -i -E 'permitrootlogin|passwordauthentication|exposeauthinfo'"
        )  # noqa: E501
        self.record("F5", judge_f5(out))

    def check_f6(self) -> None:
        _, out = self.sh(B1, "F6", "findmnt /")
        self.record("F6", ("Recorded", " ".join(out.split()[-4:]) if out else "?"))

    def check_g1(self) -> None:
        ok = self.yes("G1: does the Beacon datasheet's operating range cover -40 to +85 C?")
        note = self.ask("G1: the range as printed: ").strip()
        self.record("G1", ("Pass", note) if ok else ("Fail", note + ": outside HW-4"))

    def check_g2(self) -> None:
        ok = self.yes("G2: is there NO terminator on the tap and the logger cable?")
        self.record(
            "G2", ("Pass", "no terminator fitted") if ok else ("Fail", "a terminator is fitted")
        )

    # -- phase 4: one power-off (C2, C3, B7) ----------------------------------------------

    def power_off_checks(self) -> None:
        if "c2_before" not in self.state:
            _, out = self.sh(B1, "C2", "date -u +%s")
            self.state["c2_before"] = float(out.split()[0])
            self.state["c2_laptop"] = self.now()
            self._save_state()
            if not self.yes("Shut Beacon 1 down now for the 10-minute power-off (runs poweroff)?"):
                raise Stopped("power-off postponed")
            self.r.run(B1, "poweroff", 10.0)
            self.say("Switch the supply off, wait 10 minutes, then switch it on.")
        self.ask("Press Enter when Beacon 1 is powered on again.")
        for _ in range(60):
            rc, _ = self.r.run(B1, "true", 15.0)
            if rc == 0:
                break
            self.sleep(5.0)
        else:
            raise Stopped("Beacon 1 is not reachable after the power-off")
        _, epoch = self.sh(B1, "C2", "date -u +%s")
        after = float(epoch.split()[0])
        laptop = self.now() - float(self.state["c2_laptop"])  # type: ignore[arg-type]
        self.record("C2", judge_c2(after - float(self.state["c2_before"]), laptop))  # type: ignore[arg-type]
        _, hw = self.sh(B1, "C3", "hwclock -r")
        _, kernel = self.sh(
            B1,
            "C3",
            "dmesg | grep -i -E 'hctosys|rtc'; journalctl -k -b --no-pager | grep -i hctosys",
        )
        self.record("C3", judge_c3(kernel, after, hw))
        _, boots = self.sh(B1, "B7", "cat /root/2a-boots.txt")
        seen = [float(x) for x in boots.split() if x.isdigit()]
        new_boot = any(t > float(self.state["c2_before"]) for t in seen)  # type: ignore[arg-type]
        self.record(
            "B7",
            ("Pass", "the boot service ran at this boot")
            if new_boot
            else ("Fail", "the boot service did not run"),
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="step2a", description=__doc__.splitlines()[0])
    ap.add_argument(
        "--beacon1", required=True, help="SSH target of Beacon 1, e.g. root@192.168.250.1"
    )
    ap.add_argument("--beacon2", required=True, help="SSH target of Beacon 2")
    ap.add_argument("--can", default="can0", help="the CAN interface wired to the bus")
    ap.add_argument("--wheels", type=Path, help="folder with the logger's wheel (B3)")
    ap.add_argument("--crypto", type=Path, help="folder with the cryptography wheel (B4)")
    ap.add_argument("--only", help="comma-separated checks to (re)run, e.g. A7,C1")
    ap.add_argument("--resume", type=Path, help="an evidence folder from an earlier run")
    args = ap.parse_args(argv)
    folder = args.resume or ROOT / "docs" / "test-evidence" / f"2a_{dt.date.today().isoformat()}"
    tool = Step2a(
        SshRunner({B1: args.beacon1, B2: args.beacon2}),
        folder,
        can=args.can,
        wheels=args.wheels,
        crypto=args.crypto,
    )
    if args.only:
        for check in [c.strip().upper() for c in args.only.split(",") if c.strip()]:
            tool.results.pop(check, None)
            getattr(tool, "check_" + check.lower())()
        tool.write_sheet()
        return 0
    return tool.run()


if __name__ == "__main__":
    sys.exit(main())
