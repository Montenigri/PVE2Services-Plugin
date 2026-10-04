"""Read-only MCP tools exposed by PVE2 Drift to the Winky assistant."""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.db_adapter import get_db


async def list_managed_resources(params: dict[str, Any]) -> dict[str, Any]:
    """List IaC-declared resources tracked for drift."""
    resources = get_db().get_managed_resources()
    return {"count": len(resources), "resources": resources}


async def list_open_drifts(params: dict[str, Any]) -> dict[str, Any]:
    """List currently open drift events."""
    drifts = get_db().get_open_drifts()
    return {"count": len(drifts), "drifts": drifts}


async def list_drift_events(params: dict[str, Any]) -> dict[str, Any]:
    """List drift events, optionally filtered by status."""
    events = get_db().get_drift_events(
        status=params.get("status") or None,
        limit=int(params.get("limit", 200)),
    )
    return {"count": len(events), "events": events}
