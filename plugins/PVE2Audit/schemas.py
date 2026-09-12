from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class AuditConfig(BaseModel):
    enabled: bool = False
    proxmox_url: str = ""
    proxmox_token: str = ""
    proxmox_secret: str = ""
    sync_interval_minutes: int = 15
    collect_interval_minutes: int = 30   # background sampling cadence (15 or 30 recommended)
    analysis_window_days: int = 30       # suggestions are median-based over this window
    thresholds: Dict[str, Any] = {}
    node_balance_enabled: bool = True


class ResourceSample(BaseModel):
    entity_id: str
    node: str
    entity_type: str
    timestamp: datetime
    cpu_avg: float
    cpu_max: float
    mem_used: int
    mem_max: int
    disk_used: int
    disk_max: int


class RecommendationOut(BaseModel):
    id: int
    entity_id: str
    entity_name: Optional[str]
    entity_type: Optional[str]
    node: Optional[str]
    category: str
    severity: str
    current_value: Optional[str]
    suggested_value: Optional[str]
    rationale: Optional[str]
    created_at: datetime
    applied: bool
    dismissed: bool
    data_days: Optional[float] = None
    sample_count: Optional[int] = None


class SummaryReport(BaseModel):
    total: int
    by_severity: Dict[str, int]
    by_category: Dict[str, int]


class NodeAllocation(BaseModel):
    node: str
    total_vms: int
    total_lxcs: int
    allocated_cores: int
    allocated_memory_mb: int
    used_memory_mb: Optional[int]
    cpu_allocation_pct: Optional[float]
    memory_allocation_pct: Optional[float]
