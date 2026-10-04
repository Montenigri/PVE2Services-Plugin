"""Read-only MCP tools exposed by PVE2 Power to the Winky assistant."""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.db_adapter import get_db


async def list_schedules(params: dict[str, Any]) -> dict[str, Any]:
    """List every automatic power schedule."""
    schedules = get_db().get_power_schedules()
    return {"count": len(schedules), "schedules": schedules}


async def get_schedule(params: dict[str, Any]) -> dict[str, Any]:
    """Return the power schedule for one machine."""
    schedule = get_db().get_power_schedule(str(params.get("machine_id", "")))
    return {"found": schedule is not None, "schedule": schedule}
