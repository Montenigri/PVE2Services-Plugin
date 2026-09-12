"""Tests for PVE2Proxy plugin — proxy mapping management."""

import os

import pytest
from PVE2Services.libs.db_adapter import DBAdapter


class TestPVE2Proxy:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db_path = str(tmp_path / "test_proxy.db")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{self.db_path}"
        self.db = DBAdapter(db_url=f"sqlite:///{self.db_path}")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_mapping_lifecycle(self):
        # Create
        assert self.db.save_proxy_mapping(
            "vm/100", "Web Server", "web", "example.com", "10.0.0.1",
            port=443, ssl_enabled=True, websocket=True
        ) is True
        
        # Read
        mapping = self.db.get_proxy_mapping("vm/100")
        assert mapping is not None
        assert mapping["domain"] == "example.com"
        assert mapping["port"] == 443
        assert mapping["ssl_enabled"]  # SQLite returns 1, which is truthy
        assert mapping["websocket"]  # SQLite returns 1, which is truthy
        
        # Update
        self.db.save_proxy_mapping("vm/100", "Web Server v2", "web2", "example2.com", "10.0.0.2")
        mapping = self.db.get_proxy_mapping("vm/100")
        assert mapping["domain"] == "example2.com"
        
        # Delete
        assert self.db.delete_proxy_mapping("vm/100") is True
        assert self.db.get_proxy_mapping("vm/100") is None

    def test_mark_deployed(self):
        self.db.save_proxy_mapping("vm/100", "Test VM")
        self.db.save_proxy_mapping("vm/200", "Test VM 2")
        self.db.mark_proxy_deployed(["vm/100"])
        
        mapping1 = self.db.get_proxy_mapping("vm/100")
        mapping2 = self.db.get_proxy_mapping("vm/200")
        assert mapping1["last_deployed"] is not None
        assert mapping2["last_deployed"] is None

    def test_extra_directives(self):
        self.db.save_proxy_mapping(
            "vm/100", "Test VM", "test", "example.com", "10.0.0.1",
            extra_directives="proxy_set_header X-Custom true;"
        )
        mapping = self.db.get_proxy_mapping("vm/100")
        assert "proxy_set_header" in mapping["extra_directives"]

    def test_rate_limit(self):
        self.db.save_proxy_mapping(
            "vm/100", "Test VM", "test", "example.com", "10.0.0.1",
            rate_limit=100
        )
        mapping = self.db.get_proxy_mapping("vm/100")
        assert mapping["rate_limit"] == 100
