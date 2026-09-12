"""Tests for the PVE2Wiki history features ported from the Go project.

Covers: storage/health history recording, changelog entries with computed diff,
entity snapshots in sync_state, archiving of deleted entities, changelog page,
and the include_disks/include_cluster/include_ceph config flags.
"""

import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PVE2Services.libs.connector_config import ConnectorConfig
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.plugins.pve2wiki.providers import (
    TemplateEngine,
    compute_diff,
    format_size,
)

BASE = "/infrastructure/proxmox"


class FakeWikiClient:
    calls = []
    # Shared across instances: a real Wiki.js server keeps state between
    # the separate HTTP clients the plugin creates on every sync.
    store = {}
    next_id = 1

    def __init__(self, url, token):
        FakeWikiClient.calls.append(self)

    async def find_page_by_path(self, path, locale="en"):
        for p in FakeWikiClient.store.values():
            if p["path"] == path:
                return {"id": p["id"], "path": p["path"], "title": p["title"]}
        return None

    async def create_page(self, path, title, content, locale="en", tags=None):
        pid = FakeWikiClient.next_id
        FakeWikiClient.next_id += 1
        FakeWikiClient.store[pid] = {"id": pid, "path": path, "title": title, "content": content}
        return {"id": pid}

    async def update_page(self, page_id, path, title, content, locale="en"):
        FakeWikiClient.store[page_id].update(path=path, title=title, content=content)
        return {"id": page_id}

    async def move_page(self, page_id, new_path, locale="en"):
        FakeWikiClient.store[page_id]["path"] = new_path
        return {}

    async def delete_page(self, page_id):
        del FakeWikiClient.store[page_id]
        return {}

    async def close(self):
        pass


class FakePveClient:
    node_status = "online"
    storage_present = True

    async def get_nodes(self):
        return [{
            "id": "pve1", "name": "pve1", "type": "node", "status": self.node_status,
            "memory_mb": 8192, "maxcpu": 8, "cpu_load": 0.1, "uptime_sec": 90061,
            "hardware_info": {"networks": [], "pci": [
                {"id": "01:00.0", "device_name": "RTX 3080"},
                {"id": "03:00.0", "device_name": ""},
            ]},
        }]

    async def get_storage(self):
        if not self.storage_present:
            return []
        return [{
            "id": "storage-pve1-local", "name": "local", "type": "storage",
            "status": "active", "node": "pve1", "total_disk": 100 * 1024 ** 3,
            "used_disk": 40 * 1024 ** 3, "total_gb": 100, "used_gb": 40,
            "content": ["images", "iso"],
        }]

    async def get_disks(self):
        return [{
            "id": "disk-pve1-/dev/sda", "name": "/dev/sda", "type": "disk",
            "status": "OK", "node": "pve1", "model": "Samsung SSD",
            "serial": "S123", "disk_type": "ssd", "size_bytes": 500 * 1024 ** 3,
            "total_disk": 500 * 1024 ** 3,
        }]

    async def get_cluster_summary(self):
        return {
            "id": "cluster-mycluster", "name": "mycluster", "type": "cluster",
            "status": "quorate", "quorate": "yes", "nodes_count": 1, "nodes_online": 1,
        }

    async def get_ceph_health(self):
        return None

    async def close(self):
        pass


@pytest.fixture()
def wiki_env(tmp_path, monkeypatch):
    old_url = os.environ.get("PVE2_DB_URL")
    os.environ["PVE2_DB_URL"] = f"sqlite:///{tmp_path / 'wiki_hist.db'}"

    import PVE2Services.core.wiki_service.app.proxmox_adapter as padapter
    import PVE2Services.plugins.pve2wiki as pmod

    fake_pve = FakePveClient()

    async def fake_machines():
        return [{
            "id": "100", "name": "web", "type": "vm", "node": "pve1",
            "status": "running", "cores": 2, "memory_mb": 2048,
            "disk_gb": 32, "ip_addresses": ["10.0.0.10"],
        }]

    async def fake_create_client(*a, **k):
        return fake_pve

    monkeypatch.setattr(pmod, "get_core_machines", fake_machines)
    monkeypatch.setattr(pmod, "WikiJsClient", FakeWikiClient)
    monkeypatch.setattr(padapter, "create_client_if_possible", fake_create_client)

    ConnectorConfig().save_config("pve2wiki", {
        "enabled": True,
        "wiki_url": "http://devwiki:3000",
        "wiki_token": "test-token",
        "base_path": BASE,
        "locale": "en",
        "include_disks": False,
        "include_cluster": False,
        "include_ceph": False,
    }, enabled=True)

    FakeWikiClient.calls = []
    FakeWikiClient.store = {}
    FakeWikiClient.next_id = 1

    from PVE2Services.core.wiki_service.app.main import app

    c = TestClient(app)
    c.post("/admin/setup", json={"username": "admin", "new_password": "pve2admin"})
    r = c.post("/admin/login", json={"username": "admin", "password": "pve2admin"})
    assert r.status_code == 200, r.text

    yield {"pve": fake_pve, "client": c}
    if old_url:
        os.environ["PVE2_DB_URL"] = old_url
    else:
        os.environ.pop("PVE2_DB_URL", None)


def _sync(client):
    r = client.post("/api/plugins/pve2wiki/sync")
    assert r.status_code == 200, r.text
    return r.json()


class TestHistoryHelpers:
    def setup_method(self):
        self._old_url = os.environ.get("PVE2_DB_URL")
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.environ["PVE2_DB_URL"] = f"sqlite:///{self.db_path}"
        self.db = DBAdapter(db_url=f"sqlite:///{self.db_path}")

    def teardown_method(self):
        if self._old_url:
            os.environ["PVE2_DB_URL"] = self._old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_storage_history_roundtrip(self):
        self.db.save_storage_history("pve1", "local", total_bytes=1024, used_bytes=512,
                                     content_types="images,iso")
        rows = self.db.get_storage_history()
        assert len(rows) == 1
        assert rows[0]["node"] == "pve1"
        assert rows[0]["storage_name"] == "local"
        assert rows[0]["total_bytes"] == 1024
        assert rows[0]["content_types"] == "images,iso"
        assert rows[0]["timestamp"]

    def test_health_history_roundtrip(self):
        self.db.save_health_history("ceph", "ceph-cluster", "HEALTH_OK", "all good")
        self.db.save_health_history("disk", "pve1:/dev/sda", "FAILED")
        rows = self.db.get_health_history()
        assert len(rows) == 2
        assert rows[0]["component"] == "disk"
        assert rows[0]["status"] == "FAILED"
        assert rows[1]["details"] == "all good"

    def test_compute_diff_fields(self):
        old = {"status": "running", "cores": 2, "memory_mb": 2048,
               "ip_addresses": ["10.0.0.10"], "node": "pve1", "maxdisk": 34359738368}
        new = {"status": "stopped", "cores": 2, "memory_mb": 4096,
               "ip_addresses": ["10.0.0.11"], "node": "pve1", "maxdisk": 68719476736}
        diff = compute_diff(old, new)
        assert "status: running → stopped" in diff
        assert "RAM: 2048MB → 4096MB" in diff
        assert "10.0.0.10" in diff and "10.0.0.11" in diff
        assert "disk:" in diff and "→" in diff
        assert "cores" not in diff

    def test_compute_diff_no_change(self):
        e = {"status": "running", "cores": 2}
        assert compute_diff(e, e) == "Updated wiki page"
        assert compute_diff(None, e) == "Updated wiki page"

    def test_format_size(self):
        assert format_size(0) == "0 B"
        assert format_size(500) == "500 B"
        assert format_size(1073741824) == "1.00 GB"


class TestTemplateFilters:
    def test_entity_history_filter_renders_entries(self):
        def history_fn(entity_id):
            return [
                {"timestamp": "2026-08-26T11:00:00", "action": "updated",
                 "details": "RAM: 2048MB -> 4096MB"},
                {"timestamp": "2026-08-25T09:00:00", "action": "created"},
                {"timestamp": "2026-08-24T09:00:00", "action": "deleted"},
            ]

        eng = TemplateEngine({}, history_fn=history_fn)
        out = eng.render("vm", {"id": "100", "name": "web"})
        assert "- **2026-08-26**: RAM: 2048MB -> 4096MB" in out
        assert "- **2026-08-25**: Created" in out
        assert "- **2026-08-24**: Deleted (archived)" in out

    def test_entity_history_filter_empty_and_missing(self):
        eng = TemplateEngine({}, history_fn=lambda eid: [])
        out = eng.render("vm", {"id": "1", "name": "x"})
        assert "*No changes recorded yet.*" in out
        eng2 = TemplateEngine({})
        out2 = eng2.render("vm", {"id": "1", "name": "x"})
        assert "*No changes recorded yet.*" in out2

    def test_pci_filters(self):
        devices = [{"device_name": "GPU"}, {"device_name": ""}, {}]
        eng = TemplateEngine({})
        main = eng.env.filters["pci_main_devices"](devices)
        other = eng.env.filters["pci_other_devices"](devices)
        assert main == [{"device_name": "GPU"}]
        assert other == [{"device_name": ""}, {}]

    def test_new_default_templates_render(self):
        eng = TemplateEngine({})
        disk = eng.render("disk", {"id": "d1", "name": "/dev/sda", "node": "pve1",
                                   "status": "OK", "size_bytes": 1073741824})
        assert "# /dev/sda (pve1)" in disk
        assert "1.00 GB" in disk
        cluster = eng.render("cluster", {"id": "c1", "name": "prod", "status": "quorate",
                                         "nodes_count": 3, "quorate": "yes"})
        assert "# Cluster prod" in cluster
        ceph = eng.render("ceph", {"id": "ceph-cluster", "name": "Ceph Cluster",
                                   "status": "HEALTH_OK", "osd_total": 4, "osd_in": 4,
                                   "osd_up": 4, "mon_count": 3, "details": ""})
        assert "HEALTH_OK" in ceph
        chg = eng.render_changelog([
            {"timestamp": "2026-08-26T11:00:00", "action": "created",
             "entity_type": "vm", "entity_name": "web", "details": "Created wiki page"},
        ])
        assert "| Date | Action | Type | Name | Details |" in chg


class TestSyncPipeline:
    def test_full_lifecycle(self, wiki_env):
        client = wiki_env["client"]
        db = DBAdapter()

        # --- First sync: everything is created ---
        res = _sync(client)
        assert res["status"] == "success", res["errors"]
        # 1 vm (core machine) + 1 node + 1 storage; the changelog page is
        # maintained separately and not counted in created/updated.
        assert res["created"] == 3, res
        assert res["archived"] == 0

        log_actions = [(c["action"], c["entity_id"]) for c in db.get_changelog(50)]
        assert ("created", "100") in log_actions
        assert ("created", "storage-pve1-local") in log_actions

        # Storage history recorded during fetch
        sh = db.get_storage_history()
        assert len(sh) == 1 and sh[0]["storage_name"] == "local"

        # sync_state snapshot stored with hash + entity data
        states = {s["id"]: s for s in db.get_all_sync_states()}
        assert states["100"]["hash"]
        assert json.loads(states["100"]["entity_data"])["name"] == "web"
        assert not states["100"]["archived"]

        # Changelog page published
        assert any(p["path"].endswith("/changelog") for p in FakeWikiClient.store.values())

        # --- Second sync without changes: nothing to do ---
        res2 = _sync(client)
        assert res2["created"] == 0 and res2["updated"] == 0

        # --- Third sync after a real change: update with diff ---
        FakePveClient.node_status = "offline"
        res3 = _sync(client)
        assert res3["updated"] == 1, res3
        upd = [c for c in db.get_changelog(50) if c["action"] == "updated"]
        assert any("status: online → offline" in c["details"] for c in upd)

        # The pushed page must ALREADY include the change happening in this
        # very sync (render happens after the entry is prepared).
        node_page = next(p for p in FakeWikiClient.store.values()
                         if p["path"] == "infrastructure/proxmox/node/pve1")
        assert "status: online → offline" in node_page["content"]

        # --- Fourth sync after deletion: archive ---
        FakePveClient.storage_present = False
        res4 = _sync(client)
        assert res4["archived"] == 1, res4
        states = {s["id"]: s for s in db.get_all_sync_states()}
        assert states["storage-pve1-local"]["archived"]
        assert "/archive/storage/" in states["storage-pve1-local"]["wiki_path"]
        moved = [p for p in FakeWikiClient.store.values() if "archive" in p["path"]]
        assert moved
        deleted = [c for c in db.get_changelog(50) if c["action"] == "deleted"]
        assert any(c["entity_id"] == "storage-pve1-local" for c in deleted)

    def test_include_disks_flag(self, wiki_env):
        client = wiki_env["client"]
        db = DBAdapter()
        cfg_manager = ConnectorConfig()
        _sync(client)  # baseline without disks

        cfg = cfg_manager.get_config("pve2wiki")
        cfg["include_disks"] = True
        cfg_manager.save_config("pve2wiki", cfg, enabled=True)

        res = _sync(client)
        disk_rows = [p for p in db.get_wiki_pages() if p["entity_type"] == "disk"]
        health = [h for h in db.get_health_history() if h["component"] == "disk"]
        assert res["created"] >= 1 or disk_rows or health
        assert len(disk_rows) == 1
        assert disk_rows[0]["entity_id"] == "disk-pve1-/dev/sda"
        assert len(health) == 1
        assert health[0]["item_id"] == "pve1:/dev/sda"

    def test_include_cluster_flag(self, wiki_env):
        client = wiki_env["client"]
        db = DBAdapter()
        cfg_manager = ConnectorConfig()
        cfg = cfg_manager.get_config("pve2wiki")
        cfg["include_cluster"] = True
        cfg_manager.save_config("pve2wiki", cfg, enabled=True)

        _sync(client)
        cluster_pages = [p for p in db.get_wiki_pages() if p["entity_type"] == "cluster"]
        assert len(cluster_pages) == 1
        assert cluster_pages[0]["entity_id"] == "cluster-mycluster"


class TestTimezoneAwareTimestamps:
    def setup_method(self):
        self._old_tz = os.environ.get("PVE2_TIMEZONE")

    def teardown_method(self):
        if self._old_tz:
            os.environ["PVE2_TIMEZONE"] = self._old_tz
        else:
            os.environ.pop("PVE2_TIMEZONE", None)

    def test_local_now_respects_timezone(self, monkeypatch):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        monkeypatch.setenv("PVE2_TIMEZONE", "Europe/Rome")
        from PVE2Services.libs.timeutil import local_now

        now_local = datetime.strptime(local_now(), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo("Europe/Rome")
        )
        diff = abs((now_local - datetime.now(timezone.utc)).total_seconds())
        assert diff < 5

    def test_default_is_utc(self, monkeypatch):
        monkeypatch.delenv("PVE2_TIMEZONE", raising=False)
        from PVE2Services.libs.timeutil import local_now, local_tz

        assert str(local_tz()) == "UTC"
        assert len(local_now()) == 19

    def test_changelog_written_in_local_time(self, tmp_path, monkeypatch):
        old_url = os.environ.get("PVE2_DB_URL")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{tmp_path / 'tz.db'}"
        monkeypatch.setenv("PVE2_TIMEZONE", "Europe/Rome")
        try:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo

            db = DBAdapter(db_url=f"sqlite:///{tmp_path / 'tz.db'}")
            db.save_changelog("updated", "vm", "901", "test", "RAM change")
            row = db.get_changelog(1)[0]
            ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=ZoneInfo("Europe/Rome")
            )
            assert abs((ts - datetime.now(timezone.utc)).total_seconds()) < 5
        finally:
            if old_url:
                os.environ["PVE2_DB_URL"] = old_url
            else:
                os.environ.pop("PVE2_DB_URL", None)
