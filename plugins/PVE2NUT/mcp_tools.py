"""Read-only MCP tools exposed by PVE2 NUT to the Winky assistant."""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.db_adapter import get_db


async def list_devices(params: dict[str, Any]) -> dict[str, Any]:
    """List every monitored UPS name."""
    devices = get_db().get_nut_devices()
    return {"count": len(devices), "devices": devices}


async def last_reading(params: dict[str, Any]) -> dict[str, Any]:
    """Return the most recent reading for one UPS."""
    reading = get_db().get_last_nut_reading(str(params.get("ups_name", "")))
    return {"found": reading is not None, "reading": reading}


async def get_history(params: dict[str, Any]) -> dict[str, Any]:
    """Return UPS history samples for the last ``hours`` hours."""
    samples = get_db().get_nut_history(
        str(params.get("ups_name", "")),
        hours=int(params.get("hours", 24)),
        limit=int(params.get("limit", 1000)),
    )
    return {"count": len(samples), "samples": samples}


async def list_events(params: dict[str, Any]) -> dict[str, Any]:
    """List recent UPS events, optionally for one UPS."""
    events = get_db().get_nut_events(
        ups_name=params.get("ups_name") or None,
        limit=int(params.get("limit", 100)),
    )
    return {"count": len(events), "events": events}
