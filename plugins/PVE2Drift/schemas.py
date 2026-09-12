"""Pydantic models for the PVE2Drift plugin."""

from typing import List, Optional

from pydantic import BaseModel, Field


class DriftConfig(BaseModel):
    enabled: bool = False
    check_interval_seconds: int = 3600
    tracked_fields: List[str] = Field(
        default_factory=lambda: ["cores", "memory_mb", "disk_gb", "node", "vmid"]
    )
    unmanaged_to_audit: bool = True


class CanonicalResource(BaseModel):
    """Provider-agnostic normalized view of a declared IaC resource.

    Schema designed on the richest superset among the supported providers
    (bpg/proxmox); fields a narrower provider (Telmate) does not cover stay
    None.
    """

    resource_address: str
    resource_type: str
    provider: str = "bpg"
    node: Optional[str] = None
    vmid: Optional[int] = None
    cores: Optional[int] = None
    memory_mb: Optional[int] = None
    disk_gb: Optional[int] = None
    tags: List[str] = Field(default_factory=list)


class IngestResult(BaseModel):
    ingested: int
    resolved: int
    skipped_types: int = 0


class DriftCheckResult(BaseModel):
    checked: int
    opened: int
    resolved: int
    missing: int
    unmanaged: int
    errors: List[str] = Field(default_factory=list)


class ApiKeyCreate(BaseModel):
    environment: str = "default"
