from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DNSConfig(BaseModel):
    enabled: bool = False
    domain: str = ""
    pihole_enabled: bool = False
    pihole_url: str = ""
    pihole_token: str = ""
    pihole_api_version: str = "v5"
    adguard_enabled: bool = False
    adguard_url: str = ""
    adguard_username: str = ""
    adguard_password: str = ""
    auto_sync: bool = False
    sync_interval_minutes: int = 30


class DNSRecordIn(BaseModel):
    machine_id: str
    machine_name: str = ""
    hostname: str = ""
    ip_address: str = ""
    enabled: bool = True


class DNSRecordOut(BaseModel):
    id: int
    machine_id: str
    machine_name: str = ""
    hostname: str = ""
    ip_address: str = ""
    enabled: bool = True
    last_synced: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SyncResult(BaseModel):
    status: str
    pihole: Optional[dict] = None
    adguard: Optional[dict] = None
    records_synced: int = 0
    errors: List[str] = []
