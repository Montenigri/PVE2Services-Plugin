"""PVE2Wiki — Pydantic models for Wiki.js config, pages, sync."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WikiJsConfig(BaseModel):
    enabled: bool = False
    wiki_url: str = ""
    wiki_token: str = ""
    base_path: str = "/infrastructure/proxmox"
    locale: str = "en"
    auto_sync: bool = False
    sync_interval_minutes: int = 60
    include_disks: bool = False
    include_cluster: bool = False
    include_ceph: bool = False
    wiki_orphan_handling: str = "recreate"


class TemplateUpdate(BaseModel):
    type: str
    content: str


class WikiPage(BaseModel):
    path: str
    title: str
    content: str
    entity_type: str = ""
    entity_id: str = ""
    synced: bool = False


class SyncResult(BaseModel):
    status: str
    created: int = 0
    updated: int = 0
    archived: int = 0
    errors: list[str] = []
    details: list[WikiPage] = []


class SyncStatus(BaseModel):
    total_pages: int = 0
    last_sync: Optional[datetime] = None
    last_status: str = "pending"
