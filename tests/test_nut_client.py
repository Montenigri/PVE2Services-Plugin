"""Tests for the PVE2NUT protocol client (against a fake upsd)."""

import socket
import socketserver
import threading

import pytest
from PVE2Services.plugins.PVE2NUT.nut_client import (
    DEFAULT_PORT,
    NUTClient,
    NUTConnectionError,
    NUTError,
    NUTProtocolError,
    _unescape,
    validate_host,
)

DEFAULT_VARS = {
    "ups.status": "OL CHRG",
    "battery.charge": "100",
    "battery.runtime": "1830",
    "ups.load": "22",
    "ups.realpower": "140",
    "ups.power": "210",
    "input.voltage": "230.0",
    "output.voltage": "230.0",
    "battery.voltage": "27.30",
    "device.model": 'Smart-UPS "X" 750',
}


class _FakeNUTHandler(socketserver.StreamRequestHandler):
    def handle(self):
        state = self.server.state
        for raw in self.rfile:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            parts = line.split(maxsplit=2)
            head = parts[0]
            if head == "LIST" and len(parts) >= 2:
                if parts[1] == "UPS":
                    body = "".join(
                        f'UPS {name} "{state["ups"].get(name, "")}"\n'
                        for name in state["ups"]
                    )
                    self.wfile.write(f"BEGIN LIST UPS\n{body}END LIST UPS\n".encode())
                elif parts[1] == "VAR" and len(parts) == 3:
                    ups = parts[2].strip()
                    vars_ = state["vars"].get(ups)
                    if vars_ is None:
                        self.wfile.write("ERR UNKNOWN-UPS\n".encode())
                    else:
                        body = "".join(
                            f'VAR {ups} {k} "{v}"\n' for k, v in vars_.items()
                        )
                        self.wfile.write(f"BEGIN LIST VAR {ups}\n{body}END LIST VAR {ups}\n".encode())
                elif parts[1] == "CMD" and len(parts) == 3:
                    ups = parts[2].strip()
                    cmds = state["commands"].get(ups, [])
                    body = "".join(f"CMD {ups} {c}\n" for c in cmds)
                    self.wfile.write(f"BEGIN LIST CMD {ups}\n{body}END LIST CMD {ups}\n".encode())
                elif parts[1] == "CLIENT" and len(parts) == 3:
                    ups = parts[2].strip()
                    clients = state["clients"].get(ups, [])
                    body = "".join(f"CLIENT {ups} {c}\n" for c in clients)
                    self.wfile.write(f"BEGIN LIST CLIENT {ups}\n{body}END LIST CLIENT {ups}\n".encode())
                else:
                    self.wfile.write(b"ERR INVALID-ARGUMENT\n")
            elif head == "GET" and len(parts) == 3 and parts[1] == "VAR":
                ups, var = parts[2].split(maxsplit=1)
                value = state["vars"].get(ups.strip(), {}).get(var.strip())
                if value is None:
                    self.wfile.write(b"ERR VAR-NOT-SUPPORTED\n")
                else:
                    self.wfile.write(f'VAR {ups.strip()} {var.strip()} "{value}"\n'.encode())
            elif head == "INSTCMD" and len(parts) >= 2:
                state["received"].append(line)
                ups = parts[1]
                cmd = parts[2].strip() if len(parts) > 2 else ""
                if cmd in state["commands"].get(ups, []):
                    self.wfile.write(f"OK INSTCMD {cmd} EXECUTED\n".encode())
                else:
                    self.wfile.write(b"ERR UNKNOWN-COMMAND\n")
            elif head == "SETVAR":
                state["received"].append(line)
                self.wfile.write(b"OK VAR-SET\n")
            elif head == "USERNAME":
                state["received"].append(line)
                self.wfile.write(b"OK USERNAME-SET-IMMEDIATELY\n")
            elif head == "PASSWORD":
                state["received"].append(line)
                self.wfile.write(b"OK PASSWORD-ACCEPTED\n")
            elif head == "VER":
                self.wfile.write(b"2.8.0\n")
            elif head == "NETVER":
                self.wfile.write(b"1.2\n")
            else:
                self.wfile.write(b"ERR UNKNOWN-COMMAND\n")
            self.wfile.flush()


class FakeNUTServer:
    """In-process fake upsd for tests."""

    def __init__(self, ups: dict[str, str] | None = None,
                 vars: dict[str, dict] | None = None,
                 commands: dict[str, list] | None = None,
                 clients: dict[str, list] | None = None):
        names = ups or {"office-ups": "Office UPS"}
        self.state = {
            "ups": names,
            "vars": vars or {name: dict(DEFAULT_VARS) for name in names},
            "commands": commands or {name: ["beeper.on", "beeper.off", "test.battery.start"] for name in names},
            "clients": clients or {},
            "received": [],
        }
        self._server = socketserver.TCPServer(("127.0.0.1", 0), _FakeNUTHandler)
        self._server.allow_reuse_address = True
        self._server.state = self.state
        self.host, self.port = self._server.server_address
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def set_vars(self, ups: str, updates: dict[str, str]):
        self.state["vars"].setdefault(ups, {}).update(updates)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server():
    srv = FakeNUTServer().start()
    yield srv
    srv.stop()


class TestParseHelpers:
    def test_unescape(self):
        assert _unescape(r'with \" quote') == 'with " quote'
        assert _unescape(r"back\\slash") == r"back\slash"

    def test_validate_host_blocks_metadata(self):
        for bad in ("169.254.169.254", "metadata.google.internal", "100.100.100.200", "169.254.10.1"):
            with pytest.raises(NUTError):
                validate_host(bad)

    def test_validate_host_allows_lan_and_localhost(self):
        assert validate_host("127.0.0.1") == "127.0.0.1"
        assert validate_host(" nut.home.lan ") == "nut.home.lan"
        with pytest.raises(NUTError):
            validate_host("")


class TestNUTClientQueries:
    def test_list_ups(self, server):
        with NUTClient(server.host, server.port) as c:
            ups = c.list_ups()
        assert ups == [{"name": "office-ups", "description": "Office UPS"}]

    def test_list_vars_parses_quotes(self, server):
        with NUTClient(server.host, server.port) as c:
            vars_ = c.list_vars("office-ups")
        assert vars_["ups.status"] == "OL CHRG"
        assert vars_["battery.charge"] == "100"
        assert vars_["device.model"] == 'Smart-UPS "X" 750'

    def test_get_var(self, server):
        with NUTClient(server.host, server.port) as c:
            assert c.get_var("office-ups", "ups.load") == "22"

    def test_get_var_unknown(self, server):
        with NUTClient(server.host, server.port) as c:
            with pytest.raises(NUTProtocolError) as exc:
                c.get_var("office-ups", "nonexistent.var")
        assert exc.value.code == "VAR-NOT-SUPPORTED"

    def test_list_ups_unknown_device(self, server):
        with NUTClient(server.host, server.port) as c:
            with pytest.raises(NUTProtocolError) as exc:
                c.list_vars("ghost-ups")
        assert exc.value.code == "UNKNOWN-UPS"

    def test_list_commands(self, server):
        with NUTClient(server.host, server.port) as c:
            cmds = c.list_commands("office-ups")
        assert cmds == ["beeper.on", "beeper.off", "test.battery.start"]

    def test_list_clients(self, server):
        server.state["clients"]["office-ups"] = ["192.168.1.10", "192.168.1.11"]
        with NUTClient(server.host, server.port) as c:
            assert c.list_clients("office-ups") == ["192.168.1.10", "192.168.1.11"]

    def test_versions(self, server):
        with NUTClient(server.host, server.port) as c:
            assert c.server_version() == "2.8.0"
            assert c.protocol_version() == "1.2"


class TestNUTClientCommands:
    def test_run_command_without_auth(self, server):
        with NUTClient(server.host, server.port) as c:
            assert c.run_command("office-ups", "beeper.off") is True
        received = [r for r in server.state["received"] if r.startswith("INSTCMD")]
        assert received == ["INSTCMD office-ups beeper.off"]

    def test_run_command_with_auth_sends_credentials(self, server):
        with NUTClient(server.host, server.port, username="admin", password="secret") as c:
            assert c.run_command("office-ups", "beeper.off") is True
        received = server.state["received"]
        assert "USERNAME admin" in received
        assert "PASSWORD secret" in received
        assert "INSTCMD office-ups beeper.off" in received
        # credentials sent before the command
        assert received.index("USERNAME admin") < received.index("INSTCMD office-ups beeper.off")

    def test_run_command_unknown(self, server):
        with NUTClient(server.host, server.port) as c:
            with pytest.raises(NUTProtocolError) as exc:
                c.run_command("office-ups", "shutdown.reboot")
        assert exc.value.code == "UNKNOWN-COMMAND"

    def test_set_var(self, server):
        with NUTClient(server.host, server.port, username="admin", password="x") as c:
            assert c.set_var("office-ups", "ups.delay.shutdown", "60") is True


class TestNUTClientConnectionErrors:
    def test_connect_refused(self):
        port = _free_port()
        with pytest.raises(NUTConnectionError):
            with NUTClient("127.0.0.1", port, timeout=1):
                pass

    def test_validate_host_applied_in_constructor(self):
        with pytest.raises(NUTError):
            NUTClient("169.254.169.254")

    def test_send_when_not_connected(self):
        c = NUTClient("127.0.0.1", DEFAULT_PORT)
        with pytest.raises(NUTConnectionError):
            c.list_ups()
