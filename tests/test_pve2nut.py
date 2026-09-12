"""Tests for the PVE2NUT plugin — poller, DB lifecycle and API endpoints."""

import os

import pytest
from PVE2Services.libs.db_adapter import DBAdapter
from test_nut_client import DEFAULT_VARS, FakeNUTServer


@pytest.fixture
def nut_server():
    srv = FakeNUTServer().start()
    yield srv
    srv.stop()


def _reset_cache():
    import PVE2Services.plugins.PVE2NUT as nut
    with nut._cache_lock:
        nut._cache["at"] = 0.0
        nut._cache["devices"] = {}
        nut._cache["servers"] = []


def _config(servers, **overrides):
    cfg = {
        "enabled": True,
        "servers": servers,
        "poll_interval_seconds": 60,
        "prune_days": 30,
        "notify_on_battery": True,
        "notify_low_battery": True,
        "notify_ups_online": False,
        "notify_comm_lost": True,
        "notify_comm_restored": False,
    }
    cfg.update(overrides)
    return cfg


class TestPoller:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        self._old_url = os.environ.get("PVE2_DB_URL")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{tmp_path / 'test_nut.db'}"
        self.db = DBAdapter(f"sqlite:///{tmp_path / 'test_nut.db'}")
        _reset_cache()
        yield
        if self._old_url:
            os.environ["PVE2_DB_URL"] = self._old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_classify_status(self):
        from PVE2Services.plugins.PVE2NUT.poller import classify_status
        assert classify_status("OL")["state"] == "online"
        assert classify_status("OL CHRG")["label"] == "Online"
        assert classify_status("OB DISCHRG")["state"] == "on_battery"
        assert classify_status("OB LB")["state"] == "low_battery"
        assert classify_status("RB")["state"] == "replace_battery"
        assert classify_status("BYPASS")["state"] == "bypass"
        assert classify_status("")["state"] == "unknown"

    def test_first_poll_no_events(self, nut_server):
        import asyncio

        from PVE2Services.plugins.PVE2NUT.poller import run_poll

        result = asyncio.run(run_poll(_config([
            {"label": "s1", "host": nut_server.host, "port": nut_server.port}
        ]), self.db))
        assert not result["errors"]
        assert len(result["devices"]) == 1
        device = result["devices"][0]
        assert device["name"] == "office-ups"
        assert device["state"] == "online"
        assert device["serving_server"] == "s1"
        assert device["metrics"]["battery_charge"] == 100.0
        assert result["events"] == []
        assert self.db.get_nut_devices() == ["office-ups"]

    def test_status_change_generates_event_and_notification(self, nut_server, monkeypatch):
        import asyncio

        from PVE2Services.plugins.PVE2NUT.poller import run_poll

        config = _config([{"label": "s1", "host": nut_server.host, "port": nut_server.port}])
        asyncio.run(run_poll(config, self.db))

        calls = []

        async def fake_send_notification(title, description="", fields=None,
                                         event_type="custom", source=""):
            calls.append({"title": title, "event_type": event_type, "fields": fields})
            return {"sent": 1, "providers": 1, "errors": []}

        import PVE2Services.plugins.PVE2Notify.bridge as bridge
        monkeypatch.setattr(bridge, "send_notification", fake_send_notification)

        nut_server.set_vars("office-ups", {"ups.status": "OB DISCHRG", "battery.charge": "60"})
        result = asyncio.run(run_poll(config, self.db))
        assert [e["event_type"] for e in result["events"]] == ["on_battery"]
        assert len(calls) == 1
        assert "office-ups" in calls[0]["title"]
        assert calls[0]["event_type"] == "on_battery"

        # Back online -> ups_online event (disabled by default in config)
        nut_server.set_vars("office-ups", {"ups.status": "OL CHRG", "battery.charge": "100"})
        result = asyncio.run(run_poll(config, self.db))
        assert [e["event_type"] for e in result["events"]] == ["ups_online"]
        assert len(calls) == 1  # ups_online not notified (notify_ups_online=False)

        # No new event when the status does not change
        result = asyncio.run(run_poll(config, self.db))
        assert result["events"] == []

    def test_disabled_notification_toggle(self, nut_server, monkeypatch):
        import asyncio

        from PVE2Services.plugins.PVE2NUT.poller import run_poll

        config = _config([{"label": "s1", "host": nut_server.host, "port": nut_server.port}],
                         notify_on_battery=False)

        async def fake_send_notification(title, description="", fields=None,
                                         event_type="custom", source=""):
            return {"sent": 1, "providers": 1, "errors": []}

        import PVE2Services.plugins.PVE2Notify.bridge as bridge
        monkeypatch.setattr(bridge, "send_notification", fake_send_notification)

        asyncio.run(run_poll(config, self.db))
        nut_server.set_vars("office-ups", {"ups.status": "OB DISCHRG"})
        result = asyncio.run(run_poll(config, self.db))
        # Event is recorded but no notification delivered
        assert [e["event_type"] for e in result["events"]] == ["on_battery"]
        assert result["notified"] == 0

    def test_comm_lost_and_restored(self, nut_server):
        import asyncio

        from PVE2Services.plugins.PVE2NUT.poller import run_poll

        config = _config([{"label": "s1", "host": nut_server.host, "port": nut_server.port}])
        asyncio.run(run_poll(config, self.db))

        # Server dies -> device vanishes -> comm_lost
        nut_server.stop()
        result = asyncio.run(run_poll(config, self.db))
        assert result["devices"] == []
        types = [e["event_type"] for e in result["events"]]
        assert types == ["comm_lost"]

        # A device that stays lost is not reported twice
        result = asyncio.run(run_poll(config, self.db))
        assert result["events"] == []

        # A fresh server with the same device -> comm_restored
        restored = FakeNUTServer().start()
        try:
            config["servers"] = [{"label": "s1", "host": restored.host, "port": restored.port}]
            result = asyncio.run(run_poll(config, self.db))
            types = [e["event_type"] for e in result["events"]]
            assert types == ["comm_restored"]
        finally:
            restored.stop()

    def test_failover_between_servers(self, nut_server):
        import asyncio

        from PVE2Services.plugins.PVE2NUT.poller import run_poll

        backup = FakeNUTServer().start()
        try:
            config = _config([
                {"label": "primary", "host": nut_server.host, "port": nut_server.port},
                {"label": "backup", "host": backup.host, "port": backup.port},
            ])
            result = asyncio.run(run_poll(config, self.db))
            device = result["devices"][0]
            assert device["serving_server"] == "primary"
            assert set(device["servers"]) == {"primary", "backup"}

            # Primary dies -> backup takes over, same device identity
            nut_server.stop()
            result = asyncio.run(run_poll(config, self.db))
            device = result["devices"][0]
            assert device["serving_server"] == "backup"
            # No comm_lost: the device is still visible through the backup
            assert result["events"] == []
        finally:
            backup.stop()

    def test_prune(self, nut_server):
        import asyncio

        from PVE2Services.plugins.PVE2NUT.poller import run_poll

        config = _config([{"label": "s1", "host": nut_server.host, "port": nut_server.port}])
        asyncio.run(run_poll(config, self.db))
        assert self.db.prune_nut_history(days=30) == 0
        assert self.db.prune_nut_events(days=90) == 0


class TestNutDB:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        self._old_url = os.environ.get("PVE2_DB_URL")
        self.db = DBAdapter(f"sqlite:///{tmp_path / 'test_nut_db.db'}")
        yield
        if self._old_url:
            os.environ["PVE2_DB_URL"] = self._old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_reading_and_history(self):
        self.db.save_nut_reading("ups1", "OL", battery_charge=100.0, ups_load=10.0,
                                 vars={"ups.status": "OL"})
        self.db.save_nut_reading("ups1", "OB", battery_charge=90.0, ups_load=20.0,
                                 vars={"ups.status": "OB"})
        history = self.db.get_nut_history("ups1", hours=1)
        assert len(history) == 2
        assert history[0]["battery_charge"] == 100.0
        assert history[1]["status"] == "OB"
        last = self.db.get_last_nut_reading("ups1")
        assert last["status"] == "OB"
        assert last["vars"]["ups.status"] == "OB"

    def test_history_hours_filter(self):
        self.db.save_nut_reading("ups1", "OL")
        assert len(self.db.get_nut_history("ups1", hours=1)) == 1

    def test_events(self):
        self.db.save_nut_event("ups1", "on_battery", from_status="OL", to_status="OB")
        self.db.save_nut_event("ups2", "comm_lost")
        assert len(self.db.get_nut_events()) == 2
        only1 = self.db.get_nut_events(ups_name="ups1")
        assert len(only1) == 1 and only1[0]["from_status"] == "OL"
        # get_nut_devices derives from readings, not events
        assert self.db.get_nut_devices() == []


class TestNutAPI:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, nut_server):
        self._old_url = os.environ.get("PVE2_DB_URL")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{tmp_path / 'test_nut_api.db'}"
        self.server = nut_server
        _reset_cache()
        from fastapi.testclient import TestClient
        from PVE2Services.core.wiki_service.app.main import app

        self.client = TestClient(app)
        self.client.post("/admin/setup", json={"username": "admin", "new_password": "pve2admin"})
        r = self.client.post("/admin/login", json={"username": "admin", "password": "pve2admin"})
        assert r.status_code == 200
        yield
        if self._old_url:
            os.environ["PVE2_DB_URL"] = self._old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)
        _reset_cache()

    def _save_config(self, **overrides):
        body = {
            "enabled": True,
            "servers": [{"label": "s1", "host": str(self.server.host),
                         "port": self.server.port}],
        }
        body.update(overrides)
        return self.client.post("/api/plugins/pve2nut/config", json=body)

    def test_requires_auth(self):
        from fastapi.testclient import TestClient
        from PVE2Services.core.wiki_service.app.main import app

        anon = TestClient(app)
        r = anon.get("/api/plugins/pve2nut/info")
        assert r.status_code == 401

    def test_info(self):
        r = self.client.get("/api/plugins/pve2nut/info")
        assert r.status_code == 200
        assert r.json()["plugin"] == "pve2nut"

    def test_config_roundtrip_with_encrypted_password(self):
        r = self._save_config(servers=[{"label": "s1", "host": str(self.server.host),
                                        "port": self.server.port,
                                        "username": "admin", "password": "secret"}])
        assert r.status_code == 200 and r.json()["saved"] is True
        # Raw DB value must be encrypted
        import json

        from PVE2Services.libs.connector_config import ConnectorConfig
        from sqlalchemy import text
        cm = ConnectorConfig()
        with cm.engine.connect() as conn:
            row = conn.execute(
                text("SELECT config FROM connector_config WHERE connector_id = :id"),
                {"id": "pve2nut"}).fetchone()
        raw = json.loads(row[0])
        assert raw["servers"][0]["password"] != "secret"
        assert "secret" not in raw["servers"][0]["password"]
        # API returns the decrypted password (same behavior as PVE2Notify)
        r = self.client.get("/api/plugins/pve2nut/config")
        assert r.json()["configured"] is True
        assert r.json()["config"]["servers"][0]["password"] == "secret"

    def test_config_validation(self):
        r = self.client.post("/api/plugins/pve2nut/config",
                             json={"enabled": True, "servers": [{"label": "", "host": ""}]})
        assert r.status_code == 422

    def test_test_endpoint(self):
        self._save_config()
        r = self.client.post("/api/plugins/pve2nut/test")
        data = r.json()
        assert data["tested"] is True
        assert data["devices_found"] == 1
        assert data["results"][0]["ups_count"] == 1

    def test_sync_and_devices(self):
        self._save_config()
        r = self.client.post("/api/plugins/pve2nut/sync")
        data = r.json()
        assert data["devices"][0]["name"] == "office-ups"
        assert data["devices"][0]["status"] == DEFAULT_VARS["ups.status"]

        # /devices serves the fresh cache without re-polling
        self.server.set_vars("office-ups", {"ups.status": "OB DISCHRG"})
        r = self.client.get("/api/plugins/pve2nut/devices")
        assert r.json()["devices"][0]["status"] == DEFAULT_VARS["ups.status"]

    def test_history_and_events(self):
        self._save_config()
        self.client.post("/api/plugins/pve2nut/sync")
        r = self.client.get("/api/plugins/pve2nut/history/office-ups?hours=1")
        assert r.json()["ups_name"] == "office-ups"
        assert len(r.json()["readings"]) == 1

        r = self.client.get("/api/plugins/pve2nut/events")
        assert r.json()["events"] == []

    def test_commands_endpoints(self):
        self._save_config()
        self.client.post("/api/plugins/pve2nut/sync")

        r = self.client.get("/api/plugins/pve2nut/commands/office-ups")
        assert "beeper.off" in r.json()["commands"]

        r = self.client.get("/api/plugins/pve2nut/clients/office-ups")
        assert r.json()["clients"] == []

        r = self.client.post("/api/plugins/pve2nut/command/office-ups/beeper.off")
        assert r.json()["executed"] is True

        r = self.client.post("/api/plugins/pve2nut/command/office-ups/unknown.cmd")
        assert r.json()["executed"] is False

    def test_scheduler_lifecycle(self):
        self._save_config()
        r = self.client.post("/api/plugins/pve2nut/scheduler/start")
        assert r.json()["started"] is True
        assert r.json()["interval_seconds"] == 60
        r = self.client.get("/api/plugins/pve2nut/scheduler/status")
        assert r.json()["running"] is True
        r = self.client.post("/api/plugins/pve2nut/scheduler/stop")
        assert r.json()["stopped"] is True
        r = self.client.get("/api/plugins/pve2nut/scheduler/status")
        assert r.json()["running"] is False

    def test_admin_page(self):
        self._save_config()
        r = self.client.get("/admin/pve2nut")
        assert r.status_code == 200
        assert "PVE2 NUT" in r.text
