"""Tests for PVE2Wiki plugin — wiki page management."""

import os

import pytest
from PVE2Services.libs.db_adapter import DBAdapter


class TestPVE2Wiki:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db_path = str(tmp_path / "test_wiki.db")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{self.db_path}"
        self.db = DBAdapter(db_url=f"sqlite:///{self.db_path}")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_wiki_page_upsert(self):
        assert self.db.upsert_wiki_page(
            "vm/100", "vm", "/wiki/vm/test-vm", 123, "Test VM", "hash_abc"
        ) is True
        
        page = self.db.get_wiki_page("vm/100")
        assert page is not None
        assert page["entity_type"] == "vm"
        assert page["wiki_path"] == "/wiki/vm/test-vm"
        assert page["wiki_page_id"] == 123
        assert page["title"] == "Test VM"
        assert page["content_hash"] == "hash_abc"
        assert page["last_synced"] is not None

    def test_wiki_page_update(self):
        self.db.upsert_wiki_page("vm/100", "vm", "/wiki/vm/old", 123, "Old Title", "hash1")
        self.db.upsert_wiki_page("vm/100", "vm", "/wiki/vm/new", 456, "New Title", "hash2")
        
        page = self.db.get_wiki_page("vm/100")
        assert page["wiki_path"] == "/wiki/vm/new"
        assert page["title"] == "New Title"
        assert page["content_hash"] == "hash2"

    def test_wiki_pages_list(self):
        self.db.upsert_wiki_page("vm/100", "vm", "/wiki/vm1", 1, "VM1", "h1")
        self.db.upsert_wiki_page("vm/200", "vm", "/wiki/vm2", 2, "VM2", "h2")
        self.db.upsert_wiki_page("node/1", "node", "/wiki/node1", 3, "Node1", "h3")
        
        pages = self.db.get_wiki_pages()
        assert len(pages) == 3

    def test_wiki_page_delete(self):
        self.db.upsert_wiki_page("vm/100", "vm", "/wiki/vm", 1, "VM", "h")
        assert self.db.delete_wiki_page("vm/100") is True
        assert self.db.get_wiki_page("vm/100") is None
        assert self.db.delete_wiki_page("vm/100") is False

    def test_wiki_page_nonexistent(self):
        assert self.db.get_wiki_page("nonexistent") is None
