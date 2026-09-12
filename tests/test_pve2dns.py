"""Tests for PVE2DNS plugin — DNS record management."""

import os

import pytest
from PVE2Services.libs.db_adapter import DBAdapter


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
