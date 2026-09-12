"""Pure-Python client for the NUT (Network UPS Tools) protocol.

Implements the subset of the upsd text protocol (TCP, default port 3493)
needed for monitoring and control:

    LIST UPS | LIST VAR <ups> | GET VAR <ups> <var> | LIST CMD <ups>
    LIST CLIENT <ups> | INSTCMD <ups> <cmd> | SETVAR <ups> <var> "<value>"
    USERNAME/PASSWORD (auth for privileged ops) | VER | NETVER

No external dependencies — the protocol is a simple line-based text protocol
(the same one PeaNUT implements in TypeScript).
"""

import logging
import re
import socket

logger = logging.getLogger("pve2nut")

DEFAULT_PORT = 3493
DEFAULT_TIMEOUT = 5.0

# Hosts that must never be contacted from a web-context request (metadata
# endpoints). Private/LAN hosts and localhost are allowed — a NUT server is
# commonly on the host itself or on the LAN.
_BLOCKED_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "100.100.100.200",
    "metadata",
}

_VAR_RE = re.compile(r'^VAR\s+(\S+)\s+(\S+)\s+"(.*)"\s*$')
_UPS_RE = re.compile(r'^UPS\s+(\S+)(?:\s+"(.*)")?\s*$')
_CMD_RE = re.compile(r"^CMD\s+(\S+)\s+(\S+)\s*$")
_CLIENT_RE = re.compile(r"^CLIENT\s+(\S+)\s+(\S+)\s*$")


class NUTError(Exception):
    """Base error for NUT client failures."""


class NUTConnectionError(NUTError):
    """Could not connect or lost the connection to upsd."""


class NUTProtocolError(NUTError):
    """upsd answered with an ERR response."""

    def __init__(self, code: str, command: str = ""):
        self.code = code
        self.command = command
        super().__init__(f"NUT error {code}" + (f" (command: {command})" if command else ""))


def validate_host(host: str) -> str:
    """Validate a NUT server hostname; returns the host or raises NUTError."""
    h = (host or "").strip()
    if not h:
        raise NUTError("NUT server host is required")
    if h.lower() in _BLOCKED_HOSTS or h.startswith("169.254."):
        raise NUTError(f"Blocked NUT server host: {h}")
    return h


def _unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


class NUTClient:
    """A single-connection NUT client. Use as a context manager."""

    def __init__(self, host: str, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT,
                 username: str = "", password: str = ""):
        self.host = validate_host(host)
        self.port = int(port)
        self.timeout = float(timeout)
        self.username = (username or "").strip()
        self.password = (password or "").strip()
        self._sock: socket.socket | None = None
        self._rfile = None

    # -- connection ---------------------------------------------------------

    def __enter__(self) -> "NUTClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise NUTConnectionError(f"Cannot connect to {self.host}:{self.port}: {e}") from e
        sock.settimeout(self.timeout)
        self._sock = sock
        self._rfile = sock.makefile("r", encoding="utf-8", newline="\n")

    def close(self) -> None:
        try:
            if self._rfile:
                self._rfile.close()
        except Exception:
            pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._rfile = None

    # -- protocol -----------------------------------------------------------

    def _send(self, command: str) -> list[str]:
        """Send a command and collect the response block.

        The block is the list of payload lines (inside BEGIN/END for LIST
        commands). Raises NUTProtocolError on ERR responses.
        """
        if self._sock is None or self._rfile is None:
            raise NUTConnectionError("Not connected")
        first_word = command.split(" ", 1)[0]
        try:
            self._sock.sendall((command + "\n").encode("utf-8"))
        except OSError as e:
            raise NUTConnectionError(f"Connection lost during {first_word!r}: {e}") from e

        payload: list[str] = []
        in_block = False
        while True:
            try:
                raw = self._rfile.readline()
            except (OSError, TimeoutError) as e:
                raise NUTConnectionError(f"Timeout reading response to {first_word!r}: {e}") from e
            if not raw:
                raise NUTConnectionError(f"Connection closed by server during {first_word!r}")
            line = raw.rstrip("\n")
            if line.startswith("ERR "):
                raise NUTProtocolError(line[4:].strip(), command)
            if line.startswith("BEGIN "):
                in_block = True
                continue
            if line.startswith("END "):
                return payload
            if in_block:
                payload.append(line)
                continue
            return [line]

    def authenticate(self) -> None:
        """Send USERNAME/PASSWORD when configured (needed for INSTCMD/SETVAR)."""
        if self.username:
            self._send(f"USERNAME {self.username}")
        if self.password:
            self._send(f"PASSWORD {self.password}")

    # -- queries ------------------------------------------------------------

    def server_version(self) -> str:
        lines = self._send("VER")
        return lines[0] if lines else ""

    def protocol_version(self) -> str:
        lines = self._send("NETVER")
        return lines[0] if lines else ""

    def list_ups(self) -> list[dict]:
        """List UPS devices on the server: [{name, description}]."""
        out = []
        for line in self._send("LIST UPS"):
            m = _UPS_RE.match(line)
            if m:
                out.append({"name": m.group(1), "description": _unescape(m.group(2) or "")})
        return out

    def list_vars(self, ups: str) -> dict[str, str]:
        """All variables of a UPS as {var: value}."""
        out: dict[str, str] = {}
        for line in self._send(f"LIST VAR {ups}"):
            m = _VAR_RE.match(line)
            if m:
                out[m.group(2)] = _unescape(m.group(3))
        return out

    def get_var(self, ups: str, var: str) -> str:
        for line in self._send(f"GET VAR {ups} {var}"):
            m = _VAR_RE.match(line)
            if m:
                return _unescape(m.group(3))
        raise NUTProtocolError("EMPTY-RESPONSE", f"GET VAR {ups} {var}")

    def list_commands(self, ups: str) -> list[str]:
        """Available instant commands for a UPS (e.g. beeper.on, test.battery.start)."""
        out = []
        for line in self._send(f"LIST CMD {ups}"):
            m = _CMD_RE.match(line)
            if m:
                out.append(m.group(2))
        return out

    def list_clients(self, ups: str) -> list[str]:
        """IPs of clients (monitoring hosts) connected to a UPS."""
        out = []
        for line in self._send(f"LIST CLIENT {ups}"):
            m = _CLIENT_RE.match(line)
            if m:
                out.append(m.group(2))
        return out

    def run_command(self, ups: str, command: str) -> bool:
        """Execute an instant command (INSTCMD). Requires auth on most setups."""
        self.authenticate()
        self._send(f"INSTCMD {ups} {command}")
        return True

    def set_var(self, ups: str, var: str, value: str) -> bool:
        """Set a writable variable (SETVAR). Requires auth on most setups."""
        self.authenticate()
        safe = value.replace("\\", "\\\\").replace('"', '\\"')
        self._send(f'SETVAR {ups} {var} "{safe}"')
        return True
