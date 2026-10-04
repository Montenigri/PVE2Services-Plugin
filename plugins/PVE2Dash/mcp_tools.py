"""Read-only MCP tools exposed by PVE2 Dash to the Winky assistant."""

from __future__ import annotations

from collections import Counter
from typing import Any

from PVE2Services.libs.plugin_base import get_core_health, get_core_machines


async def dashboard_summary(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate cluster health: machine counts by type and status."""
    machines = await get_core_machines()
    by_type = Counter(str(m.get("type", "unknown")) for m in machines)
    by_status = Counter(str(m.get("status", "unknown")) for m in machines)
    health = await get_core_health()
    return {
        "total": len(machines),
        "by_type": dict(by_type),
        "by_status": dict(by_status),
        "health": health,
    }
