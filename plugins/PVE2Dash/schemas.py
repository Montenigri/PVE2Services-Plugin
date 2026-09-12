from typing import List

from pydantic import BaseModel


class DashConfig(BaseModel):
    enabled: bool = False
    proxmox_url: str = ""
    proxmox_token: str = ""
    proxmox_secret: str = ""


class HistorySample(BaseModel):
    timestamp: int  # unix epoch seconds — Proxmox RRD format, used as-is by the frontend
    cpu: float = 0
    mem: float = 0
    mem_used: int = 0
    mem_max: int = 0
    disk: float = 0
    disk_used: int = 0
    disk_max: int = 0
    netin: int = 0
    netout: int = 0


class HistoryResponse(BaseModel):
    entity_id: str
    samples: List[HistorySample] = []
    timeframe: str = "day"
