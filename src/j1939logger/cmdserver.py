"""cmdserver: the command socket (docs/modules.md section 4, v1, frozen for step 7).

Layer 5, inside ``main``. Built to DC-21 (STS-23).

One JSON line per connection on a Unix socket
(``/run/j1939-logger/cmd.sock`` on the Beacon, ``main --socket PATH``
elsewhere)::

    {"proto": 1, "cmd": "...", "args": {...}, "operator": "...", "reason": "..."}

``check(request)`` refuses an unknown protocol version, a missing or unknown
command, or arguments that are not an object, with a reason and the next step;
it never changes state. A valid request is queued for the session's main loop,
which answers one command at a time (``Session.commands``); while one is waiting,
another is refused as busy. The reply is ``{"proto": 1, "ok": true, "result":
...}`` or ``{"proto": 1, "ok": false, "error": "...", "next": "..."}``.

``request(path, message)`` is the client side that ``j1939cmd`` uses.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from j1939logger.session import Session

__all__ = ["CmdServer", "COMMANDS", "PROTO", "check", "check_path", "request", "Pending"]

PROTO = 1
COMMANDS = frozenset({
    "status", "login", "logout", "train_start", "train_status", "train_finish", "train_confirm",
    "events", "approve", "remove", "clear", "config_show", "config_push", "inventory_show",
    "retrieve_list", "retrieved", "restart", "retrain",
})  # fmt: skip
MAX_LINE = 4 * 1024 * 1024  # a config push is the largest request
REPLY_TIMEOUT_S = 60.0
MAX_PATH_BYTES = 107  # sockaddr_un.sun_path is 108 bytes with the closing NUL


def _refused(error: str, next_step: str) -> dict[str, Any]:
    return {"proto": PROTO, "ok": False, "error": error, "next": next_step}


def check(req: Any) -> Optional[dict[str, Any]]:
    """The refusal for a malformed request, or None when it can be queued (cmd_bad_proto)."""
    if not isinstance(req, dict):
        return _refused("the request is not a JSON object", "update j1939ctl")
    if req.get("proto") != PROTO:
        return _refused(
            f"unknown protocol version {req.get('proto')!r}; the logger speaks {PROTO}",
            "use the j1939ctl version that matches the logger software",
        )
    cmd = req.get("cmd")
    if not isinstance(cmd, str) or cmd not in COMMANDS:
        return _refused(f"unknown command {cmd!r}", "run j1939ctl --help")
    if not isinstance(req.get("args", {}), dict):
        return _refused("args must be a JSON object", f"run j1939ctl {cmd} --help")
    return None


def check_path(path: Path) -> Optional[str]:
    """Why the socket cannot be made at ``path``, or None (a clear startup fault, not a crash)."""
    if not hasattr(socket, "AF_UNIX"):
        return "Unix sockets are not available on this system"
    n = len(os.fsencode(str(path)))
    if n > MAX_PATH_BYTES:
        return f"command socket path is {n} bytes; the limit is {MAX_PATH_BYTES}: {path}"
    return None


@dataclass
class Pending:
    """One queued request and its reply, filled by the main loop."""

    request: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    reply: Optional[dict[str, Any]] = None


class CmdServer:
    def __init__(self, path: Path, session: Session) -> None:
        self.path = Path(path)
        self._session = session
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._busy = threading.Lock()

    def submit(self, req: dict[str, Any]) -> dict[str, Any]:
        """Check, queue for the main loop and wait for the answer (one at a time)."""
        bad = check(req)
        if bad is not None:
            self._session.diag.log("warning", "cmdserver", str(bad["error"]))
            return bad
        if not self._busy.acquire(blocking=False):
            return _refused("another command is running", "retry in a moment")  # cmd_busy
        try:
            pending = Pending(req)
            self._session.commands.put(pending)
            if not pending.done.wait(REPLY_TIMEOUT_S) or pending.reply is None:
                return _refused("the logger did not answer in time", "run status, then retry")
            return pending.reply
        finally:
            self._busy.release()

    def start(self) -> None:
        problem = check_path(self.path)
        if problem is not None:
            raise OSError(problem)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()  # left over from a previous run
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.path))
        os.chmod(self.path, 0o660)
        sock.listen(4)
        sock.settimeout(0.2)
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, name="cmdserver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._sock is not None:
            self._sock.close()
        try:
            self.path.unlink()
        except OSError:
            pass

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:  # top of the thread: a bad client never stops the logger (rule 14)
                self._answer(conn)
            except Exception as exc:
                self._session.diag.log("error", "cmdserver", f"{type(exc).__name__}: {exc}")
            finally:
                conn.close()

    def _answer(self, conn: socket.socket) -> None:
        conn.settimeout(10)
        data = b""
        while b"\n" not in data and len(data) < MAX_LINE:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        try:
            req = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            reply = _refused("the request is not JSON", "update j1939ctl")
        else:
            reply = self.submit(req)
        conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))


def request(
    path: Path, message: dict[str, Any], timeout: float = REPLY_TIMEOUT_S
) -> dict[str, Any]:
    """Send one request to the service and return its reply; OSError if it is not running."""
    if not hasattr(socket, "AF_UNIX"):
        raise OSError("Unix sockets are not available on this system")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(path))
        s.sendall((json.dumps(message) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    reply: dict[str, Any] = json.loads(data.decode("utf-8"))
    return reply
