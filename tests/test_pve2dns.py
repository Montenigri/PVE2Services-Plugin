"""Tests for PVE2DNS plugin — DNS record management."""

import asyncio
import os

import pytest
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.plugins.PVE2DNS.providers import PiHoleProvider


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _LogoutClient:
    """Async client stub that records DELETE calls (Pi-hole v6 logout)."""

    instances = []

    def __init__(self, *a, **k):
        self.calls = []
        _LogoutClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def delete(self, url, **kw):
        self.calls.append(("delete", url, kw))
        return _Resp(204, {})


class _FakePiHoleV6:
    """Minimal async client emulating the Pi-hole v6 endpoints we use."""

    def __init__(self, hosts=None):
        self.hosts = list(hosts or [])
        self.calls = []

    async def post(self, url, **kw):
        self.calls.append(("post", url, kw))
        return _Resp(200, {"session": {"sid": "SID", "validity": 1800}})

    async def get(self, url, **kw):
        self.calls.append(("get", url, kw))
        return _Resp(200, {"config": {"dns": {"hosts": list(self.hosts)}}})

    async def put(self, url, **kw):
        self.calls.append(("put", url, kw))
        entry = url.rsplit("/", 1)[-1].replace("%20", " ")
        if entry in self.hosts:
            return _Resp(400, {})
        self.hosts.append(entry)
        return _Resp(201, {})

    async def delete(self, url, **kw):
        self.calls.append(("delete", url, kw))
        entry = url.rsplit("/", 1)[-1].replace("%20", " ")
        if entry in self.hosts:
            self.hosts.remove(entry)
            return _Resp(204, {})
        return _Resp(404, {})


class TestPVE2DNS:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db_path = str(tmp_path / "test_dns.db")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{self.db_path}"
        self.db = DBAdapter(db_url=f"sqlite:///{self.db_path}")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_dns_record_lifecycle(self):
        # Create
        assert self.db.save_dns_record("vm/100", "Web Server", "web.example.com", "10.0.0.1") is True
        
        # Read
        record = self.db.get_dns_record("vm/100")
        assert record is not None
        assert record["machine_name"] == "Web Server"
        assert record["hostname"] == "web.example.com"
        assert record["ip_address"] == "10.0.0.1"
        assert record["enabled"]  # SQLite returns 1, which is truthy
        
        # Update
        self.db.save_dns_record("vm/100", "Web Server v2", "web2.example.com", "10.0.0.2")
        record = self.db.get_dns_record("vm/100")
        assert record["hostname"] == "web2.example.com"
        
        # Delete
        assert self.db.delete_dns_record("vm/100") is True
        assert self.db.get_dns_record("vm/100") is None

    def test_bulk_save(self):
        records = [
            {"machine_id": f"vm/{i}", "machine_name": f"VM{i}", "hostname": f"vm{i}.example.com", "ip_address": f"10.0.0.{i}"}
            for i in range(1, 6)
        ]
        saved = self.db.bulk_save_dns_records(records)
        assert saved == 5
        assert len(self.db.get_dns_records()) == 5

    def test_mark_synced(self):
        self.db.save_dns_record("vm/100", "Test", "test.example.com", "10.0.0.1")
        self.db.mark_dns_record_synced(["vm/100"])
        record = self.db.get_dns_record("vm/100")
        assert record["last_synced"] is not None


class TestPiHoleProviderV6:
    def test_api_version_branch(self):
        assert PiHoleProvider("http://p", "pw", "v6")._is_v6 is True
        assert PiHoleProvider("http://p", "pw", "6")._is_v6 is True
        assert PiHoleProvider("http://p", "pw", None)._is_v6 is True  # default v6
        assert PiHoleProvider("http://p", "pw", "v5")._is_v6 is False

    def test_v6_auth_is_cached(self):
        p = PiHoleProvider("http://pihole", "pw", "v6")
        c = _FakePiHoleV6()
        h1 = asyncio.run(p._v6_headers(c))
        h2 = asyncio.run(p._v6_headers(c))
        assert h1 == {"X-FTL-SID": "SID"} == h2
        assert sum(1 for call in c.calls if call[0] == "post") == 1

    def test_v6_add_is_idempotent_and_deletes(self):
        p = PiHoleProvider("http://pihole", "pw", "v6")
        c = _FakePiHoleV6()
        headers = {"X-FTL-SID": "SID"}
        assert asyncio.run(p._v6_add(c, headers, "10.0.0.5 web.lab.local")) is True
        assert c.hosts == ["10.0.0.5 web.lab.local"]
        # second add is a no-op (still succeeds, no duplicate)
        assert asyncio.run(p._v6_add(c, headers, "10.0.0.5 web.lab.local")) is True
        assert c.hosts == ["10.0.0.5 web.lab.local"]
        # entry is URL-encoded in the request path
        put_url = next(call[1] for call in c.calls if call[0] == "put")
        assert "%20" in put_url and " " not in put_url
        # delete works and a repeat delete (404) is tolerated
        assert asyncio.run(p._v6_delete(c, headers, "10.0.0.5 web.lab.local")) is True
        assert c.hosts == []
        assert asyncio.run(p._v6_delete(c, headers, "10.0.0.5 web.lab.local")) is True


    def test_v6_close_logs_out(self, monkeypatch):
        from PVE2Services.plugins.PVE2DNS import providers

        p = providers.PiHoleProvider("http://pihole", "pw", "v6")
        c = _FakePiHoleV6()
        asyncio.run(p._v6_headers(c))
        assert p._sid == "SID"
        _LogoutClient.instances.clear()
        monkeypatch.setattr(providers.httpx, "AsyncClient", _LogoutClient)
        asyncio.run(p.close())
        assert p._sid is None
        calls = [call for inst in _LogoutClient.instances for call in inst.calls]
        assert any(call[0] == "delete" and call[1].endswith("/api/auth") for call in calls)
        # v5 has no session to release
        p5 = providers.PiHoleProvider("http://pihole", "hash", "v5")
        assert asyncio.run(p5.close()) is None


class _AghState:
    def __init__(self):
        self.rewrites = []
        self.calls = []


class _AghClient:
    def __init__(self, state):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kw):
        self.state.calls.append(("get", url, kw))
        if url.endswith("/control/rewrite/list"):
            return _Resp(200, list(self.state.rewrites))
        if url.endswith("/control/status"):
            return _Resp(200, {"version": "v0.107.79"})
        return _Resp(200, {})

    async def post(self, url, **kw):
        self.state.calls.append(("post", url, kw))
        body = kw.get("json") or {}
        if url.endswith("/control/rewrite/add"):
            self.state.rewrites.append(
                {"domain": body.get("domain"), "answer": body.get("answer")}
            )
            return _Resp(200, {})
        if url.endswith("/control/rewrite/delete"):
            self.state.rewrites = [
                r
                for r in self.state.rewrites
                if not (
                    r["domain"] == body.get("domain")
                    and r["answer"] == body.get("answer")
                )
            ]
            return _Resp(200, {})
        return _Resp(200, {})


class TestAdGuardProvider:
    def _install(self, monkeypatch, state):
        from PVE2Services.plugins.PVE2DNS import providers

        monkeypatch.setattr(providers.httpx, "AsyncClient", lambda *a, **k: _AghClient(state))

    def test_create_is_idempotent_and_deletes(self, monkeypatch):
        from PVE2Services.plugins.PVE2DNS.providers import AdGuardProvider

        state = _AghState()
        self._install(monkeypatch, state)
        p = AdGuardProvider("http://agh", "admin", "pw")
        assert asyncio.run(p.create_record("web.lab.local", "10.0.0.5")) is True
        # second create must NOT add a duplicate (AdGuard would store it)
        assert asyncio.run(p.create_record("web.lab.local", "10.0.0.5")) is True
        assert state.rewrites == [{"domain": "web.lab.local", "answer": "10.0.0.5"}]
        assert asyncio.run(p.delete_record("web.lab.local", "10.0.0.5")) is True
        assert state.rewrites == []
        # deleting an absent rewrite is a no-op success
        assert asyncio.run(p.delete_record("web.lab.local", "10.0.0.5")) is True

    def test_test_connection(self, monkeypatch):
        from PVE2Services.plugins.PVE2DNS.providers import AdGuardProvider

        state = _AghState()
        self._install(monkeypatch, state)
        p = AdGuardProvider("http://agh", "admin", "pw")
        assert asyncio.run(p.test_connection()) == {
            "connected": True,
            "api": "adguard",
            "version": "v0.107.79",
        }

    def test_close_is_noop(self):
        from PVE2Services.plugins.PVE2DNS.providers import AdGuardProvider

        p = AdGuardProvider("http://agh", "admin", "pw")
        assert asyncio.run(p.close()) is None
