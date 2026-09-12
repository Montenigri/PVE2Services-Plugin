import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from .schemas import GenericMachine


class MachineCache:
    def __init__(self):
        self._machines: Dict[str, GenericMachine] = {}
        self._last_sync: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def swap(self, machines: Dict[str, GenericMachine], timestamp: datetime):
        async with self._lock:
            self._machines = machines
            self._last_sync = timestamp

    async def get_all(self) -> List[GenericMachine]:
        async with self._lock:
            return list(self._machines.values())

    async def get_filtered(
        self,
        status: Optional[str] = None,
        machine_type: Optional[str] = None,
        node: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[GenericMachine]:
        async with self._lock:
            result = list(self._machines.values())
        if status:
            result = [m for m in result if m.status == status]
        if machine_type:
            result = [m for m in result if m.type == machine_type]
        if node:
            result = [m for m in result if m.node == node]
        if tag:
            result = [m for m in result if tag in m.tags]
        return result

    async def get_by_id(self, machine_id: str) -> Optional[GenericMachine]:
        async with self._lock:
            return self._machines.get(machine_id)

    async def set_status(self, machine_id: str, status: str) -> bool:
        """Update one machine's status in place (e.g. after a power action)."""
        async with self._lock:
            m = self._machines.get(machine_id)
            if m is None:
                return False
            m.status = status
            if status != "running":
                m.uptime_sec = 0
            return True

    async def stats(self) -> dict:
        async with self._lock:
            total = len(self._machines)
            by_type: Dict[str, int] = {}
            by_status: Dict[str, int] = {}
            for m in self._machines.values():
                by_type[m.type] = by_type.get(m.type, 0) + 1
                by_status[m.status] = by_status.get(m.status, 0) + 1
            return {
                "total": total,
                "by_type": by_type,
                "by_status": by_status,
                "last_sync": self._last_sync,
            }

    async def last_sync(self) -> Optional[datetime]:
        async with self._lock:
            return self._last_sync
