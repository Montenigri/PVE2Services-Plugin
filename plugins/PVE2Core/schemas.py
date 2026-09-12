from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class CoreConfig(BaseModel):
    enabled: bool = False
    proxmox_url: str = ""
    proxmox_token: str = ""
    proxmox_secret: str = ""
    proxmox_insecure: bool = True
    sync_interval_minutes: int = 30


class CoreSetup(BaseModel):
    proxmox_url: str
    proxmox_token: str
    proxmox_secret: str
    proxmox_insecure: bool = True


class GenericMachine(BaseModel):
    id: str
    name: str = ""
    type: str  # "vm" or "lxc"
    node: str
    status: str = "unknown"
    uptime_sec: int = 0
    cores: int = 0
    memory_mb: int = 0
    used_mem_mb: int = 0
    disk_gb: int = 0
    used_disk_gb: int = 0
    ip_addresses: List[str] = []
    tags: List[str] = []


class HealthResponse(BaseModel):
    status: str = "ok"
    last_sync: Optional[datetime] = None
    proxmox_connected: bool = False
    cache_size: int = 0


class ClusterResponse(BaseModel):
    cluster_name: str = ""
    quorum_status: str = "unknown"
    ceph_health: Optional[str] = None


class StorageInfo(BaseModel):
    id: str
    name: str
    node: str
    type: str = ""
    total_gb: int = 0
    used_gb: int = 0
    content: str = ""


class NodeInfo(BaseModel):
    id: str
    name: str
    type: str = "node"
    status: str = ""
    memory_mb: int = 0
    uptime_sec: int = 0
    maxcpu: int = 0
    cpu_load: float = 0.0


class ActionResponse(BaseModel):
    task_id: str
    action: str
    machine_id: str
    status: str = "accepted"
