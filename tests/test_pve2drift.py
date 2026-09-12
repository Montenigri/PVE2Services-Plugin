"""Tests for PVE2Drift plugin — OpenTofu drift detection."""

import os

import pytest
from fastapi.testclient import TestClient
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.plugins.PVE2Drift.engine import run_drift_check
from PVE2Services.plugins.PVE2Drift.matcher import (
    TAG_PREFIX,
    is_matching_tag,
    matching_tag_for,
)
from PVE2Services.plugins.PVE2Drift.parser import StateParseError, parse_tofu_state


def make_machine(machine_id="100", name="web", node="pve1", status="running",
                 machine_type="vm", cores=4, memory_mb=4096, disk_gb=32,
                 tags=None, **kwargs):
    """GenericMachine-shaped dict as returned by get_core_machines()."""
    return {
        "id": machine_id, "name": name, "type": machine_type, "node": node,
        "status": status, "uptime_sec": 86400, "cores": cores,
        "memory_mb": memory_mb, "used_mem_mb": 1024, "disk_gb": disk_gb,
        "used_disk_gb": 10, "ip_addresses": ["10.0.0.10"],
        "tags": tags or [], **kwargs,
    }


def make_tofu_state():
    """Minimal `tofu show -json` payload for the bpg provider."""
    return {
        "format_version": "1.2",
        "values": {
            "root_module": {
                "resources": [
                    {
                        "address": "proxmox_virtual_environment_vm.web",
                        "mode": "managed",
                        "type": "proxmox_virtual_environment_vm",
                        "name": "web",
                        "values": {
                            "node_name": "pve1", "vm_id": 100,
                            "cpu": {"cores": 4},
                            "memory": {"dedicated": 4096},
                            "disk": [{"interface": "scsi0", "size": 32}],
                            "tags": ["terraform", "web"],
                        },
                    },
                    {
                        "address": "proxmox_virtual_environment_pool.main",
                        "mode": "managed",
                        "type": "proxmox_virtual_environment_pool",
                        "values": {},
                    },
                    {
                        "address": "data.proxmox_virtual_environment_nodes.all",
                        "mode": "data",
                        "type": "proxmox_virtual_environment_nodes",
                        "values": {},
                    },
                ],
                "child_modules": [
                    {
                        "address": "module.vms",
                        "resources": [
                            {
                                "address": 'module.vms.proxmox_virtual_environment_vm.workers["w1"]',
                                "mode": "managed",
                                "type": "proxmox_virtual_environment_vm",
                                "values": {
                                    "node_name": "pve2", "vm_id": 101,
                                    "cpu": {"cores": 2},
                                    "memory": {"dedicated": 2048},
                                    "disk": [{"interface": "scsi0", "size": 16.5}],
                                    "tags": [],
                                },
                            },
                            {
                                "address": 'module.vms.proxmox_virtual_environment_vm.workers["w2"]',
                                "mode": "managed",
                                "type": "proxmox_virtual_environment_vm",
                                "values": {
                                    "node_name": "pve2", "vm_id": None,
                                    "cpu": {"cores": 2},
                                    "memory": {"dedicated": 2048},
                                    "tags": ["pve2-managed-000000000000"],
                                },
                            },
                            {
                                "address": 'module.cts.proxmox_virtual_environment_container.proxy',
                                "mode": "managed",
                                "type": "proxmox_virtual_environment_container",
                                "values": {
                                    "node_name": "pve1", "vm_id": 200,
                                    "cpu": {"cores": 1},
                                    "memory": {"dedicated": 512},
                                    "tags": ["proxy"],
                                },
                            },
                        ],
                        "child_modules": [
                            {
                                "address": "module.vms.module.nested",
                                "resources": [],
                            }
                        ],
                    }
                ],
            }
        },
    }


class TestParser:
    def test_extracts_root_and_child_resources(self):
        resources, skipped = parse_tofu_state(make_tofu_state())
        addresses = [r.resource_address for r in resources]
        assert "proxmox_virtual_environment_vm.web" in addresses
        assert 'module.vms.proxmox_virtual_environment_vm.workers["w1"]' in addresses
        assert 'module.vms.proxmox_virtual_environment_vm.workers["w2"]' in addresses
        assert 'module.cts.proxmox_virtual_environment_container.proxy' in addresses

    def test_unsupported_types_are_counted_not_parsed(self):
        resources, skipped = parse_tofu_state(make_tofu_state())
        # pool is managed but unsupported; the data source is ignored entirely
        assert skipped == 1
        assert all("pool" not in r.resource_address for r in resources)

    def test_bpg_field_mapping(self):
        resources, _ = parse_tofu_state(make_tofu_state())
        web = next(r for r in resources if r.resource_address == "proxmox_virtual_environment_vm.web")
        assert web.provider == "bpg"
        assert web.node == "pve1"
        assert web.vmid == 100
        assert web.cores == 4
        assert web.memory_mb == 4096
        assert web.disk_gb == 32
        assert "web" in web.tags

    def test_optional_vmid_stays_none(self):
        resources, _ = parse_tofu_state(make_tofu_state())
        w2 = next(r for r in resources if '"w2"' in r.resource_address)
        assert w2.vmid is None
        assert w2.cores == 2

    def test_float_disk_size_truncates_like_the_live_normalizer(self):
        resources, _ = parse_tofu_state(make_tofu_state())
        w1 = next(r for r in resources if '"w1"' in r.resource_address)
        assert w1.disk_gb == 16

    def test_malformed_payloads(self):
        for bad in ([], {"values": {}}, {"values": {"root_module": "nope"}}, {"foo": 1}):
            with pytest.raises(StateParseError):
                parse_tofu_state(bad)


class TestMatcher:
    def test_tag_is_deterministic_and_pve_safe(self):
        a = "module.foo.proxmox_virtual_environment_vm.bar[\"baz\"]"
        t1 = matching_tag_for(a)
        t2 = matching_tag_for(a)
        assert t1 == t2
        assert t1.startswith(TAG_PREFIX)
        # PVE tag charset: no colons or brackets
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./+")
        assert set(t1) <= allowed

    def test_different_addresses_different_tags(self):
        assert matching_tag_for("a.b") != matching_tag_for("a.c")

    def test_is_matching_tag(self):
        assert is_matching_tag(matching_tag_for("x"))
        assert not is_matching_tag("terraform")
        assert not is_matching_tag(TAG_PREFIX)
        assert not is_matching_tag(None)


class TestDriftDB:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db = DBAdapter(db_url=f"sqlite:///{tmp_path / 'drift.db'}")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_managed_resource_upsert(self):
        tag = matching_tag_for("mod.vm.web")
        rid = self.db.upsert_managed_resource("mod.vm.web", "proxmox_virtual_environment_vm",
                                              "bpg", tag, 100, "prod", "pve1", "{}")
        assert rid > 0
        # re-ingest updates, does not duplicate
        rid2 = self.db.upsert_managed_resource("mod.vm.web", "proxmox_virtual_environment_vm",
                                               "bpg", tag, 101, "prod", "pve2", "{}")
        assert rid2 == rid
        rows = self.db.get_managed_resources()
        assert len(rows) == 1
        assert rows[0]["last_vmid"] == 101
        assert rows[0]["node"] == "pve2"

    def test_get_by_tag_and_delete(self):
        tag = matching_tag_for("mod.vm.web")
        rid = self.db.upsert_managed_resource("mod.vm.web", "vm", "bpg", tag, None)
        assert self.db.get_managed_resource_by_tag(tag)["id"] == rid
        assert self.db.delete_managed_resource(rid) is True
        assert self.db.get_managed_resource_by_tag(tag) is None

    def test_drift_open_update_resolve(self):
        rid = self.db.upsert_managed_resource("mod.vm.web", "vm", "bpg", "pve2-managed-abc", 100)
        assert self.db.open_or_update_drift(rid, "cores", "4", "2") is True
        assert self.db.open_or_update_drift(rid, "cores", "4", "3") is False  # no duplicate
        open_rows = self.db.get_open_drifts()
        assert len(open_rows) == 1
        assert open_rows[0]["live_value"] == "3"
        assert self.db.resolve_drift(rid, "cores") is True
        assert self.db.resolve_drift(rid, "cores") is False  # already resolved
        assert self.db.get_open_drifts() == []
        events = self.db.get_drift_events()
        assert len(events) == 1
        assert events[0]["status"] == "resolved"
        assert events[0]["resource_address"] == "mod.vm.web"

    def test_resource_missing_category(self):
        rid = self.db.upsert_managed_resource("mod.vm.web", "vm", "bpg", "pve2-managed-abc", 100)
        self.db.open_or_update_drift(rid, "resource", "mod.vm.web", "",
                                     category="resource_missing")
        assert self.db.get_open_drifts()[0]["category"] == "resource_missing"

    def test_api_keys_lifecycle(self):
        key = self.db.create_api_key("production")
        assert key.startswith("pve2drift_")
        row = self.db.verify_api_key(key)
        assert row["environment"] == "production"
        assert self.db.verify_api_key("wrong") is None
        keys = self.db.list_api_keys()
        assert len(keys) == 1
        assert "key_hash" not in keys[0]  # hash never leaks in listings
        assert self.db.revoke_api_key(keys[0]["id"]) is True
        assert self.db.verify_api_key(key) is None


class TestEngine:
    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path, monkeypatch):
        old_url = os.environ.get("PVE2_DB_URL")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{tmp_path / 'drift_engine.db'}"
        self.db = DBAdapter(db_url=os.environ["PVE2_DB_URL"])

        import PVE2Services.plugins.PVE2Drift.matcher as matcher_mod

        self.machines = []

        async def fake_machines():
            return self.machines

        monkeypatch.setattr(matcher_mod, "get_core_machines", fake_machines)
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def _ingest_resource(self, address="mod.vm.web", vmid=100, cores=4,
                         memory_mb=4096, disk_gb=32, node="pve1"):
        tag = matching_tag_for(address)
        rid = self.db.upsert_managed_resource(
            address, "proxmox_virtual_environment_vm", "bpg", tag, vmid,
            "prod", node,
            declared_state='{"cores": %s, "memory_mb": %s, "disk_gb": %s, "node": "%s", "vmid": %s}'
            % (cores, memory_mb, disk_gb, node, vmid),
        )
        return rid, tag

    def test_no_drift_when_aligned(self):
        self._ingest_resource()
        self.machines = [make_machine(tags=[matching_tag_for("mod.vm.web")])]
        import asyncio
        r = asyncio.run(run_drift_check())
        assert r.checked == 1
        assert r.opened == 0
        assert self.db.get_open_drifts() == []

    def test_attribute_drift_open_no_spam_then_resolve(self):
        self._ingest_resource(cores=4)
        self.machines = [make_machine(cores=2, tags=[matching_tag_for("mod.vm.web")])]

        import asyncio
        r1 = asyncio.run(run_drift_check())
        assert r1.opened == 1
        open_rows = self.db.get_open_drifts()
        assert len(open_rows) == 1
        assert open_rows[0]["field"] == "cores"
        assert open_rows[0]["declared_value"] == "4"
        assert open_rows[0]["live_value"] == "2"

        # second identical check: no new transition, just last_detected refresh
        r2 = asyncio.run(run_drift_check())
        assert r2.opened == 0
        assert len(self.db.get_open_drifts()) == 1

        # live realigns: drift resolves
        self.machines = [make_machine(cores=4, tags=[matching_tag_for("mod.vm.web")])]
        r3 = asyncio.run(run_drift_check())
        assert r3.resolved == 1
        assert self.db.get_open_drifts() == []

    def test_resource_missing_when_tag_absent(self):
        rid, _ = self._ingest_resource()
        self.machines = [make_machine(machine_id="999", tags=["terraform"])]
        import asyncio
        r = asyncio.run(run_drift_check())
        assert r.missing == 1
        assert r.opened == 1
        open_rows = self.db.get_open_drifts()
        assert open_rows[0]["category"] == "resource_missing"

        # resource comes back: drift resolves
        self.machines = [make_machine(tags=[matching_tag_for("mod.vm.web")])]
        r2 = asyncio.run(run_drift_check())
        assert r2.resolved == 1
        assert self.db.get_open_drifts() == []

    def test_vmid_drift_is_attribute_not_join_key(self):
        # declared vmid 100, live machine id 105 but same tag: matching holds
        self._ingest_resource(vmid=100)
        self.machines = [make_machine(machine_id="105", tags=[matching_tag_for("mod.vm.web")])]
        import asyncio
        r = asyncio.run(run_drift_check())
        assert r.checked == 1
        drifts = self.db.get_open_drifts()
        assert len(drifts) == 1
        assert drifts[0]["field"] == "vmid"
        assert drifts[0]["declared_value"] == "100"
        assert drifts[0]["live_value"] == "105"

    def test_untracked_or_null_fields_ignored(self):
        rid, _ = self._ingest_resource(address="mod.vm.null", vmid=None, cores=None,
                                       memory_mb=None, disk_gb=None, node=None)
        self.machines = [make_machine(machine_id="100", tags=[matching_tag_for("mod.vm.null")])]
        import asyncio
        r = asyncio.run(run_drift_check())
        assert r.opened == 0

    def test_unmanaged_machine_goes_to_audit(self):
        self.machines = [make_machine(machine_id="300", tags=["pve2-managed-deadbeefcafe"])]
        import asyncio
        r = asyncio.run(run_drift_check())
        assert r.unmanaged == 1
        recs = self.db.get_recommendations(category="drift", active_only=True)
        assert len(recs) == 1
        assert recs[0]["entity_id"] == "unmanaged:300"
        assert recs[0]["current_value"] == "pve2-managed-deadbeefcafe"

        # second check: no duplicate recommendation
        r2 = asyncio.run(run_drift_check())
        assert r2.unmanaged == 1
        assert len(self.db.get_recommendations(category="drift", active_only=True)) == 1

    def test_drift_findings_flow_to_audit(self):
        self._ingest_resource(cores=4)
        self.machines = [make_machine(cores=2, tags=[matching_tag_for("mod.vm.web")])]
        import asyncio
        asyncio.run(run_drift_check())
        recs = self.db.get_recommendations(category="drift", active_only=True)
        assert len(recs) == 1
        assert recs[0]["entity_id"] == "drift:mod.vm.web"
        assert recs[0]["current_value"].startswith("cores:")

        # resolve dismisses the audit finding
        self.machines = [make_machine(cores=4, tags=[matching_tag_for("mod.vm.web")])]
        asyncio.run(run_drift_check())
        assert self.db.get_recommendations(category="drift", active_only=True) == []

    def test_untagged_machines_are_ignored(self):
        self.machines = [make_machine(machine_id="1", tags=["prod", "web"])]
        import asyncio
        r = asyncio.run(run_drift_check())
        assert r.unmanaged == 0
        assert r.checked == 0


class TestIngestion:
    @pytest.fixture()
    def env(self, tmp_path, monkeypatch):
        old_url = os.environ.get("PVE2_DB_URL")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{tmp_path / 'drift_ingest.db'}"
        db = DBAdapter(db_url=os.environ["PVE2_DB_URL"])
        key = db.create_api_key("ci")

        import PVE2Services.plugins.PVE2Drift.matcher as matcher_mod
        machines = []

        async def fake_machines():
            return machines

        monkeypatch.setattr(matcher_mod, "get_core_machines", fake_machines)

        from PVE2Services.core.wiki_service.app.main import app

        c = TestClient(app)
        yield {"client": c, "db": db, "key": key, "machines": machines}
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_missing_key_rejected(self, env):
        r = env["client"].post("/api/v1/state/ingest", json=make_tofu_state())
        assert r.status_code == 401

    def test_wrong_key_rejected(self, env):
        r = env["client"].post("/api/v1/state/ingest", json=make_tofu_state(),
                               headers={"Authorization": "Bearer pve2drift_bogus"})
        assert r.status_code == 401

    def test_valid_ingestion(self, env):
        r = env["client"].post("/api/v1/state/ingest", json=make_tofu_state(),
                               headers={"Authorization": f"Bearer {env['key']}"})
        assert r.status_code == 200
        body = r.json()
        assert body["ingested"] == 4
        assert body["skipped_types"] == 1
        rows = env["db"].get_managed_resources()
        assert len(rows) == 4
        web = next(x for x in rows if x["resource_address"] == "proxmox_virtual_environment_vm.web")
        assert web["last_vmid"] == 100
        assert web["cluster_id"] == "ci"
        assert '"cores": 4' in web["declared_state"]
        assert web["last_ingested_at"]

    def test_alternative_header(self, env):
        r = env["client"].post("/api/v1/state/ingest", json=make_tofu_state(),
                               headers={"X-PVE2-Api-Key": env["key"]})
        assert r.status_code == 200

    def test_reingestion_no_duplicates(self, env):
        headers = {"Authorization": f"Bearer {env['key']}"}
        env["client"].post("/api/v1/state/ingest", json=make_tofu_state(), headers=headers)
        r2 = env["client"].post("/api/v1/state/ingest", json=make_tofu_state(), headers=headers)
        assert r2.status_code == 200
        assert len(env["db"].get_managed_resources()) == 4

    def test_malformed_body(self, env):
        r = env["client"].post("/api/v1/state/ingest", json={"nope": True},
                               headers={"Authorization": f"Bearer {env['key']}"})
        assert r.status_code == 400
        r2 = env["client"].post("/api/v1/state/ingest", content=b"not json",
                                headers={"Authorization": f"Bearer {env['key']}",
                                         "Content-Type": "application/json"})
        assert r2.status_code == 400

    def test_ingestion_closes_realigned_drifts(self, env):
        # a machine drifted out of band: live cores 2, declared 4
        address = "proxmox_virtual_environment_vm.web"
        env["machines"].append(make_machine(machine_id="100", cores=2,
                                            tags=[matching_tag_for(address)]))
        headers = {"Authorization": f"Bearer {env['key']}"}
        env["client"].post("/api/v1/state/ingest", json=make_tofu_state(), headers=headers)
        # open a drift manually (as the check cycle would)
        tag = matching_tag_for(address)
        res = env["db"].get_managed_resource_by_tag(tag)
        assert env["db"].open_or_update_drift(res["id"], "cores", "4", "2") is True
        # CI re-ingests with corrected state (cores now 2 == live): drift closes
        state = make_tofu_state()
        state["values"]["root_module"]["resources"][0]["values"]["cpu"]["cores"] = 2
        r = env["client"].post("/api/v1/state/ingest", json=state, headers=headers)
        assert r.status_code == 200
        assert r.json()["resolved"] >= 1
        assert env["db"].get_open_drifts(resource_id=res["id"]) == []

    def test_revoked_key_rejected(self, env):
        keys = env["db"].list_api_keys()
        env["db"].revoke_api_key(keys[0]["id"])
        r = env["client"].post("/api/v1/state/ingest", json=make_tofu_state(),
                               headers={"Authorization": f"Bearer {env['key']}"})
        assert r.status_code == 401


class TestEndpoints:
    @pytest.fixture()
    def env(self, tmp_path, monkeypatch):
        old_url = os.environ.get("PVE2_DB_URL")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{tmp_path / 'drift_ep.db'}"
        db = DBAdapter(db_url=os.environ["PVE2_DB_URL"])

        import PVE2Services.plugins.PVE2Drift.matcher as matcher_mod
        machines = []

        async def fake_machines():
            return machines

        monkeypatch.setattr(matcher_mod, "get_core_machines", fake_machines)

        from PVE2Services.core.wiki_service.app.main import app

        c = TestClient(app)
        c.post("/admin/setup", json={"username": "admin", "new_password": "pve2admin"})
        c.post("/admin/login", json={"username": "admin", "password": "pve2admin"})
        yield {"client": c, "db": db, "machines": machines}
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_info_and_config_roundtrip(self, env):
        c = env["client"]
        info = c.get("/api/plugins/pve2drift/info").json()
        assert info["plugin"] == "pve2drift"
        r = c.post("/api/plugins/pve2drift/config", json={
            "enabled": True, "check_interval_seconds": 600,
            "tracked_fields": ["cores", "memory_mb"], "unmanaged_to_audit": False,
        })
        assert r.status_code == 200 and r.json()["saved"]
        cfg = c.get("/api/plugins/pve2drift/config").json()
        assert cfg["configured"] is True
        assert cfg["config"]["check_interval_seconds"] == 600
        assert cfg["config"]["tracked_fields"] == ["cores", "memory_mb"]

    def test_sync_requires_enabled(self, env):
        c = env["client"]
        # self-contained: force a disabled config first (the plugin's
        # config_manager binds to the DB active at app-load time, so never
        # rely on state left by other tests)
        c.post("/api/plugins/pve2drift/config", json={
            "enabled": False, "check_interval_seconds": 600,
            "tracked_fields": ["cores", "memory_mb", "disk_gb", "node", "vmid"],
            "unmanaged_to_audit": True,
        })
        r = c.post("/api/plugins/pve2drift/sync")
        assert r.json().get("error") == "Plugin not enabled"

    def test_sync_runs_check(self, env):
        c = env["client"]
        c.post("/api/plugins/pve2drift/config", json={
            "enabled": True, "check_interval_seconds": 600,
            "tracked_fields": ["cores", "memory_mb", "disk_gb", "node", "vmid"],
            "unmanaged_to_audit": True,
        })
        r = c.post("/api/plugins/pve2drift/sync")
        assert r.status_code == 200
        body = r.json()
        assert body["checked"] == 0

    def test_resources_and_drifts_listing(self, env):
        c = env["client"]
        rid = env["db"].upsert_managed_resource(
            "mod.vm.web", "proxmox_virtual_environment_vm", "bpg",
            matching_tag_for("mod.vm.web"), 100, "ci", "pve1",
            '{"cores": 4, "memory_mb": 4096, "disk_gb": 32, "node": "pve1", "vmid": 100}')
        env["db"].open_or_update_drift(rid, "cores", "4", "2")
        res = c.get("/api/plugins/pve2drift/resources").json()
        assert res["total"] == 1
        assert res["resources"][0]["open_drifts"][0]["field"] == "cores"
        drifts = c.get("/api/plugins/pve2drift/drifts?status=open").json()
        assert drifts["total"] == 1
        assert drifts["events"][0]["resource_address"] == "mod.vm.web"

    def test_api_key_management(self, env):
        c = env["client"]
        r = c.post("/api/plugins/pve2drift/apikeys", json={"environment": "prod"})
        assert r.status_code == 200
        plaintext = r.json()["key"]
        assert plaintext.startswith("pve2drift_")
        keys = c.get("/api/plugins/pve2drift/apikeys").json()["keys"]
        assert len(keys) == 1
        assert keys[0]["environment"] == "prod"
        # the plaintext must verify against the stored hash
        assert env["db"].verify_api_key(plaintext)["environment"] == "prod"
        d = c.delete(f"/api/plugins/pve2drift/apikeys/{keys[0]['id']}")
        assert d.status_code == 200
        assert env["db"].verify_api_key(plaintext) is None

    def test_tf_snippet(self, env):
        r = env["client"].get("/api/plugins/pve2drift/tf-snippet",
                              params={"address": "module.foo.proxmox_virtual_environment_vm.bar"})
        body = r.json()
        assert body["tag"] == matching_tag_for("module.foo.proxmox_virtual_environment_vm.bar")
        assert 'tags = ["pve2-managed-' in body["hcl"]

    def test_scheduler_lifecycle(self, env):
        c = env["client"]
        r = c.post("/api/plugins/pve2drift/scheduler/start", params={"interval_seconds": 3600})
        assert r.json()["started"] is True
        status = c.get("/api/plugins/pve2drift/scheduler/status").json()
        assert status["running"] is True
        r2 = c.post("/api/plugins/pve2drift/scheduler/stop")
        assert r2.json()["stopped"] is True
        status = c.get("/api/plugins/pve2drift/scheduler/status").json()
        assert status["running"] is False

    def test_admin_page_served(self, env):
        r = env["client"].get("/admin/pve2drift")
        assert r.status_code == 200
        assert "PVE2 Drift" in r.text


class TestManifest:
    def test_manifest_valid_and_core_compat(self):
        from pathlib import Path

        from PVE2Services.core.wiki_service.app.main import CORE_VERSION
        from PVE2Services.libs.plugin_manifest import load_manifest

        plugin_dir = Path(__file__).resolve().parents[1] / "plugins" / "PVE2Drift"
        m = load_manifest(plugin_dir)
        assert m.id == "pve2drift"
        assert m.trust_tier == "trusted"
        assert m.satisfies_core(CORE_VERSION)
