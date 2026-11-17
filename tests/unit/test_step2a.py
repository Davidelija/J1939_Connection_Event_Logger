"""tools/step2a.py (DC-29): the step 2a checks, against recorded Beacon output (no hardware)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("step2a", ROOT / "tools" / "step2a.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["step2a"] = module
    spec.loader.exec_module(module)
    return module


s2a = _load()
B1, B2 = s2a.B1, s2a.B2
BOOT = dt.datetime(2026, 11, 20, 10, 0, 0, tzinfo=dt.timezone.utc)

# What a healthy Beacon prints (taken from the formats of iproute2, can-utils and systemd).
DETAILS = (
    "3: can0: <NOARP,UP,LOWER_UP,ECHO> mtu 16 qdisc pfifo_fast state UP mode DEFAULT\n"
    "    link/can  promiscuity 0 minmtu 0 maxmtu 0\n"
    "    can <LISTEN-ONLY,BERR-REPORTING> state BUS-OFF restart-ms 0 termination 0\n"
)
GOOD: dict[tuple[Optional[str], str], str] = {
    (B1, "uname -r"): "5.10.120-beacon\naarch64\nNAME=Beacon Linux\n",
    (
        B1,
        "python3 --version",
    ): "Python 3.9.18\npip 23.0.1 from /usr/lib/python3/dist-packages/pip\n",
    (B1, "ip -details link show;"): DETAILS,
    (None, "ip -details link show can0"): DETAILS,
    (B2, "ip -details -statistics link show can0"): (
        "    can state ERROR-PASSIVE (berr-counter tx 128 rx 0) restart-ms 0\n"
    ),
    (B1, "sysctl"): "net.core.rmem_max = 212992\nnet.core.rmem_max = 4194304\n"
    "net.core.rmem_max = 4194304\n",
    (B1, "python3 -m venv"): "ok\n",
    (B1, "journalctl -u wdtest"): "Started Watchdog test.\nwdtest.service: Watchdog timeout (limit "
    "10s)!\nwdtest.service: Scheduled restart job.\nStarted Watchdog test.\n",
    (B1, "ls -l /dev/rtc"): "crw------- 1 root root 253, 0 /dev/rtc0\n",
    (B1, "systemctl status"): "inactive\n",
    (B1, "lsblk -f"): "mmcblk1\n`-mmcblk1p1 ext4 card 1234-5678 /media/card\n",
    (B1, "findmnt -o TARGET"): "/media/card /dev/mmcblk1p1 ext4 rw,relatime\n",
    (B1, "touch /var/lib/probe-2a"): "/dev/ubi0_0\n/dev/ubi0_0 400000 100000 300000 25% /var/lib\n",
    (B1, "ls /sys/class/leds"): "status\n",
    (B1, "cat /sys/class/leds/status/trigger"): "none [heartbeat] timer\n",
    (B1, "sshd -T"): "permitrootlogin no\npasswordauthentication no\nexposeauthinfo yes\n",
    (B1, "findmnt /"): "TARGET SOURCE FSTYPE OPTIONS\n/ /dev/ubi0_1 ubifs ro,relatime\n",
    (B1, "getent passwd"): "root:x:0:0:root:/root:/bin/sh\n",
    (
        B1,
        "dmesg | grep -i -E 'hctosys",
    ): "rtc0: setting system clock to 2026-11-20T10:00 (hctosys)\n",
}
SPAWNS: dict[tuple[str, str], str] = {
    (B1, "timeout 10 candump can0"): "  can0  18FEF100   [8]  00 00 00 00 00 00 00 00\n",
    (B1, "timeout 15 candump can0"): "  can0  18FEF100   [8]  00 00 00 00 00 00 00 00\n",
    (B2, "timeout 10 candump can0"): "  can0  18EAFF00   [3]  00 EE 00\n",
    (B1, "timeout 30 candump -e"): "  can0  20000004   [8]  ERRORFRAME controller-problem"
    "{tx-error-passive}\n",
    (B1, "timeout 10 candump -td -d"): " (000.000120)  can0  18FEF100   [8]  00 00 00 00\n",
}
ANSWERS = {
    "Your name": "Vaughan",
    "Observer": "",
    "serial": "SN-1",
    "Type BENCH": "BENCH",
    "DG services": "dgserviced",
    "only nodes": "y",
    "Disable the time sync": "y",
    "Which one": "",
    "blinking": "y",
    "steady": "y",
    "laptop reach": "y",
    "cover -40": "y",
    "range as printed": "-40 to +85 C",
    "NO terminator": "y",
    "Shut Beacon 1 down": "y",
}


class Clock:
    def __init__(self) -> None:
        self.t = BOOT.timestamp()


class _Spawned:
    def __init__(self, out: str) -> None:
        self.out = out

    def wait(self, timeout: float) -> tuple[int, str]:
        return 0, self.out


class FakeRunner:
    """Answers like a Beacon from recorded output; records every command."""

    def __init__(self, clock: Clock, overrides: Optional[dict[Any, str]] = None) -> None:
        self.clock = clock
        self.table = {**GOOD, **(overrides or {})}
        self.commands: list[tuple[str, str]] = []

    def run(
        self, role: str, command: str, timeout: float = 120.0, stdin: Optional[str] = None
    ) -> tuple[int, str]:
        self.commands.append((role, command))
        if command == "date -u +%s":
            return 0, f"{int(self.clock.t)}\n"
        if command == "poweroff":
            self.clock.t += 610.0  # ten minutes off, plus the boot
            return 255, "Connection closed"
        if command == "hwclock -r":  # the RTC keeps time with the Beacon's clock
            when = dt.datetime.fromtimestamp(self.clock.t, dt.timezone.utc)
            return 0, when.isoformat(sep=" ") + "\n"
        if command == "cat /root/2a-boots.txt":
            return 0, f"{int(self.clock.t) - 30}\n"
        for (who, key), out in self.table.items():
            if (who is None or who == role) and command.startswith(key):
                return 0, out
        return 0, ""

    def spawn(self, role: str, command: str) -> _Spawned:
        self.commands.append((role, command))
        for (who, key), out in SPAWNS.items():
            if who == role and command.startswith(key):
                return _Spawned(out)
        return _Spawned("")

    def copy(self, role: str, local_dir: Path, remote_dir: str) -> tuple[int, str]:
        self.commands.append((role, f"scp {local_dir} {remote_dir}"))
        return 0, ""


def asker(overrides: Optional[dict[str, str]] = None) -> Callable[[str], str]:
    answers = {**ANSWERS, **(overrides or {})}

    def ask(prompt: str) -> str:
        for key, value in answers.items():
            if key in prompt:
                return value
        return ""  # "press Enter"

    return ask


def tool(
    tmp_path: Path,
    runner: FakeRunner,
    clock: Clock,
    answers: Optional[dict[str, str]] = None,
    folder: str = "2a",
) -> Any:
    wheels = tmp_path / "wheels"
    wheels.mkdir(exist_ok=True)
    return s2a.Step2a(
        runner,
        tmp_path / folder,
        wheels=wheels,
        crypto=wheels,
        ask=asker(answers),
        say=lambda text: None,
        sleep=lambda s: None,
        now=lambda: clock.t,
    )


def sent(runner: FakeRunner) -> list[str]:
    return [c for _, c in runner.commands if "cangen" in c or "cansend" in c]


def test_DC_29_each_check_runs_the_procedures_commands_and_saves_evidence(tmp_path: Path) -> None:
    clock = Clock()
    runner = FakeRunner(clock)
    t = tool(tmp_path, runner, clock)
    assert t.run() == 0
    verdicts = {c: t.results[c]["verdict"] for c, _ in s2a.SHEET}
    assert all(verdicts.values()), [c for c, v in verdicts.items() if not v]  # every check ran
    assert [c for c, v in verdicts.items() if v in ("Fail", "Gap", "Manual")] == []
    evidence = tmp_path / "2a"
    assert "[B1]$ ip -details link show" in (evidence / "A1.txt").read_text("utf-8")
    a4 = (evidence / "A4.txt").read_text("utf-8")
    assert "[B1]$ cansend can0 18EAFF00#00EE00" in a4 and "18EAFF00   [3]  00 EE 00" in a4
    assert "[B1]$ systemctl stop dgserviced" in (evidence / "A2.txt").read_text("utf-8")
    sheet = (evidence / "results.md").read_text("utf-8")
    assert "| **Decision** | **Go** | |" in sheet and "Run by: Vaughan" in sheet
    assert "| D2 Writable flash | Pass | /var/lib is writable on flash with 292 MB free |" in sheet


def test_DC_29_pass_conditions_judge_recorded_outputs() -> None:
    assert s2a.judge_a1(DETAILS, "can0")[0] == "Pass"
    assert s2a.judge_a1("2: eth0: <UP>\n    link/ether 00:11\n", "can0")[0] == "Fail"
    stats_quiet = "    can state ERROR-ACTIVE (berr-counter tx 0 rx 0)\n"
    frames = SPAWNS[(B1, "timeout 15 candump can0")]
    assert (
        s2a.judge_a3(DETAILS, frames, GOOD[(B2, "ip -details -statistics link show can0")])[0]
        == "Pass"
    )
    assert s2a.judge_a3(DETAILS, frames, stats_quiet)[0] == "Fail"  # Beacon 1 acknowledged
    assert s2a.judge_a3("can <BERR-REPORTING>", frames, stats_quiet)[0] == "Fail"
    assert s2a.judge_a4(SPAWNS[(B2, "timeout 10 candump can0")])[0] == "Pass"
    assert s2a.judge_a4("")[0] == "Fail"
    assert s2a.judge_a8("termination 120", "termination 0", 0)[0] == "Pass"
    assert s2a.judge_a8("can <>", "can <>", 2)[0] == "Gap"
    assert s2a.judge_a8("termination 120", "termination 120", 2)[0] == "Fail"
    assert s2a.judge_a9(SPAWNS[(B1, "timeout 10 candump -td -d")])[0] == "Pass"
    assert s2a.judge_a9("SO_RXQ_OVFL not supported by your Linux Kernel")[0] == "Fail"
    assert s2a.judge_a10(GOOD[(B1, "sysctl")])[0] == "Pass"
    assert s2a.judge_a10("net.core.rmem_max = 212992\nsysctl: permission denied\n")[0] == "Fail"
    assert s2a.judge_b2("Python 3.9.18\npip 23.0") == ("Pass", "Python 3.9.18")
    assert s2a.judge_b2("Python 3.11.2\npip 23")[1].endswith("not 3.9, needs a DC")
    assert s2a.judge_b2("sh: python3: not found")[0] == "Gap"
    assert s2a.judge_b6(GOOD[(B1, "journalctl -u wdtest")])[0] == "Pass"
    assert s2a.judge_b6("Started Watchdog test.\n")[0] == "Gap"
    epoch = dt.datetime(2026, 11, 20, 10, 10, tzinfo=dt.timezone.utc).timestamp()
    hw = "2026-11-20 10:10:00.000000+00:00\n"
    assert s2a.judge_c3("setting system clock (hctosys)", epoch + 1, hw)[0] == "Pass"
    assert s2a.judge_c3("setting system clock (hctosys)", epoch + 60, hw)[0] == "Fail"
    assert s2a.judge_c3("", epoch, hw)[0] == "Fail"
    assert s2a.judge_c3("hctosys", epoch, "Fri Nov 20 10:10:00 2026")[0] == "Manual"
    assert s2a.judge_c2(612.0, 610.0)[0] == "Pass" and s2a.judge_c2(0.0, 610.0)[0] == "Fail"
    assert s2a.judge_d1(GOOD[(B1, "lsblk -f")], GOOD[(B1, "findmnt -o TARGET")])[0] == "Pass"
    assert s2a.judge_d1("mmcblk1\n`-mmcblk1p1 vfat\n", "")[0] == "Fail"
    assert s2a.judge_f5(GOOD[(B1, "sshd -T")])[0] == "Pass"
    assert s2a.judge_f5("permitrootlogin no\n")[0] == "Gap"


@pytest.mark.parametrize(
    ("override", "stopped_before"),
    [
        ({(B1, "ip -details link show;"): "2: eth0: <UP>\n    link/ether 00:11\n"}, "A2"),
        (
            {
                (B2, "ip -details -statistics link show can0"): "can state ERROR-ACTIVE"
                " (berr-counter tx 0 rx 0)"
            },
            "A4",
        ),  # fmt: skip
    ],
)
def test_DC_29_go_no_go_stops_after_a1_a3_or_a4_fails(
    tmp_path: Path, override: dict[Any, str], stopped_before: str
) -> None:
    clock = Clock()
    runner = FakeRunner(clock, override)
    t = tool(tmp_path, runner, clock)
    assert t.run() == 1
    assert stopped_before not in t.results  # nothing after the failed go/no-go check
    sheet = (tmp_path / "2a" / "results.md").read_text("utf-8")
    assert "| **Decision** | **No-go** | |" in sheet
    if stopped_before == "A2":
        assert sent(runner) == []  # A1 fails before anything is sent
    else:
        assert not any("cansend" in c for c in sent(runner))  # A4 never ran


def test_DC_29_results_sheet_matches_the_procedures_sheet() -> None:
    text = (ROOT / "docs" / "step-2a-procedure.md").read_text("utf-8")
    table = text.split("## 12. Results sheet", 1)[1]
    labels = [
        line.split("|")[1].strip()
        for line in table.splitlines()
        if line.startswith("| ") and not line.startswith(("| Check", "| ---", "| **Decision"))
    ]
    assert labels == [label for _, label in s2a.SHEET]


def test_DC_29_cleanup_restores_the_interfaces_and_removes_test_units(tmp_path: Path) -> None:
    clock = Clock()
    runner = FakeRunner(clock)
    assert tool(tmp_path, runner, clock).run() == 0
    tail = runner.commands[-6:]
    for role in (B1, B2):
        assert any(
            r == role and "type can bitrate 250000 listen-only off" in c and "termination 0" in c
            for r, c in tail
        )
    removed = " ".join(c for r, c in tail if r == B1)
    assert "rm -f /etc/systemd/system/wdtest.service" in removed
    assert "/etc/systemd/system/boottest.service" in removed


def test_DC_29_refuses_to_send_without_the_bench_confirmation(tmp_path: Path) -> None:
    clock = Clock()
    runner = FakeRunner(clock)
    t = tool(tmp_path, runner, clock, {"Type BENCH": "truck"})
    assert t.run() == 3
    assert sent(runner) == []
    assert "A2" not in t.results and t.results["A1"]["verdict"] == "Pass"


def test_DC_29_resume_continues_after_the_power_off(tmp_path: Path) -> None:
    clock = Clock()
    first = FakeRunner(clock)
    t = tool(tmp_path, first, clock, {"Shut Beacon 1 down": "n"})
    assert t.run() == 3  # stopped before the power-off
    assert "C2" not in t.results and "F6" in t.results
    assert not any("boottest.service" in c and "rm -f" in c for _, c in first.commands)
    clock.t += 610.0  # the operator powers it off and on by hand
    second = FakeRunner(clock)
    again = tool(tmp_path, second, clock)
    assert again.run() == 0
    assert not any(c.startswith("uname") for _, c in second.commands)  # done checks not rerun
    for check in ("C2", "C3", "B7", "B4"):
        assert again.results[check]["verdict"] == "Pass", (check, again.results[check])
    assert re.search(r"\| C2 Time across power-off \| Pass \|",
                     (tmp_path / "2a" / "results.md").read_text("utf-8"))  # fmt: skip
