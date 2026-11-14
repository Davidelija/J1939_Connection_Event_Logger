"""j1939cmd: the program SSH runs for each laptop command (docs/modules.md section 4, v1, step 7).

Layer 5, logger side. Built to DC-21 (STS-5, STS-23, LAP-15).

``ssh logger j1939cmd`` with one JSON line on standard input::

    {"cmd": "...", "args": {...}, "reason": "..."}

* The operator comes from the SSH key: OpenSSH ``ExposeAuthInfo`` names a file
  in ``SSH_USER_AUTH`` whose ``publickey`` line holds the key, whose SHA-256
  fingerprint maps to a name in the fingerprint-to-name file
  (``/etc/j1939-logger/operators``, one ``SHA256:... name`` per line, kept by
  ``release/keys.sh``). An unknown or missing key is refused for every command
  that changes the logger.
* The request goes to the service's socket (``cmdserver``) and the reply is
  printed as one JSON line.
* When the service is down (``cmd_not_running``): ``status`` is answered from
  the status file and ``retrieve_list`` from the card; anything else is refused
  with "logger not running" and the next step (STS-23 (d)).

Exit codes: 0 done, 1 refused, 2 bad input, 3 logger not running.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable, Optional, TextIO

from j1939logger.cmdserver import PROTO, request
from j1939logger.session import Session, card_files

__all__ = ["main", "fingerprint", "operator_for", "run", "EXIT_OK", "EXIT_REFUSED",
           "EXIT_BAD_INPUT", "EXIT_NOT_RUNNING"]  # fmt: skip

EXIT_OK, EXIT_REFUSED, EXIT_BAD_INPUT, EXIT_NOT_RUNNING = 0, 1, 2, 3
SOCKET = Path("/run/j1939-logger/cmd.sock")
OPERATORS = Path("/etc/j1939-logger/operators")
READ_ONLY_WHEN_DOWN = ("status", "retrieve_list")

Send = Callable[[Path, dict[str, Any]], dict[str, Any]]


def fingerprint(auth_text: str) -> Optional[str]:
    """``SHA256:...`` of the public key in an ``ExposeAuthInfo`` file, as ``ssh-keygen -l``."""
    for line in auth_text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "publickey":
            try:
                blob = base64.b64decode(parts[2], validate=True)
            except (ValueError, binascii.Error):
                return None
            digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii")
            return "SHA256:" + digest.rstrip("=")
    return None


def operator_for(fp: Optional[str], operators_text: str) -> Optional[str]:
    """The operator name for a fingerprint, from the fingerprint-to-name file."""
    if fp is None:
        return None
    for line in operators_text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, name = line.partition(" ")
        if key == fp and name.strip():
            return name.strip()
    return None


def _reply(ok: bool, **fields: Any) -> dict[str, Any]:
    return {"proto": PROTO, "ok": ok, **fields}


def _when_down(cmd: str, card: Optional[Path]) -> tuple[dict[str, Any], int]:
    if cmd == "status" and card is not None:
        path = card / "status.json"
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            body = None
        if isinstance(body, dict):
            body["service"] = "not running"
            return _reply(True, result=body), EXIT_OK
    if cmd == "retrieve_list" and card is not None:
        return _reply(True, result={"files": card_files(card), "service": "not running"}), EXIT_OK
    return (
        _reply(False, error="logger not running",
               next="restart the logger (power-cycle it, or ask an admin to start the service)"),
        EXIT_NOT_RUNNING,
    )  # fmt: skip


def run(
    line: str,
    *,
    operator: Optional[str],
    socket_path: Path,
    card: Optional[Path],
    send: Send = request,
) -> tuple[dict[str, Any], int]:
    """Handle one request line; the reply and the exit code."""
    try:
        req = json.loads(line)
    except ValueError:
        return _reply(
            False, error="the request is not JSON", next="update j1939ctl"
        ), EXIT_BAD_INPUT
    if not isinstance(req, dict) or not isinstance(req.get("cmd"), str):
        return _reply(False, error="no command given", next="run j1939ctl --help"), EXIT_BAD_INPUT
    cmd = req["cmd"]
    if cmd in Session.CHANGING and operator is None:
        return (
            _reply(False, error="this SSH key is not an operator key",
                   next="install your key with release/keys.sh"),
            EXIT_REFUSED,
        )  # fmt: skip
    message = {"proto": PROTO, "cmd": cmd, "args": req.get("args") or {}, "operator": operator,
               "reason": req.get("reason")}  # fmt: skip
    try:
        reply = send(socket_path, message)
    except (OSError, ValueError):
        return _when_down(cmd, card)
    return reply, (EXIT_OK if reply.get("ok") else EXIT_REFUSED)


def main(
    argv: Optional[Sequence[str]] = None,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> int:
    ap = argparse.ArgumentParser(prog="j1939cmd", description=__doc__.splitlines()[0])
    ap.add_argument("--socket", type=Path, default=SOCKET)
    ap.add_argument("--card", type=Path, help="the card, for answers while the service is down")
    ap.add_argument("--operators", type=Path, default=OPERATORS)
    args = ap.parse_args(argv)
    env = os.environ if environ is None else environ
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    fp = None
    auth = env.get("SSH_USER_AUTH")
    if auth:
        try:
            fp = fingerprint(Path(auth).read_text(encoding="utf-8"))
        except OSError:
            fp = None
    try:
        operators = args.operators.read_text(encoding="utf-8")
    except OSError:
        operators = ""
    reply, code = run(stdin.readline(), operator=operator_for(fp, operators),
                      socket_path=args.socket, card=args.card)  # fmt: skip
    stdout.write(json.dumps(reply) + "\n")
    stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
