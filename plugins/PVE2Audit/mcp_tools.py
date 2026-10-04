"""Read-only MCP tools exposed by PVE2 Audit to the Winky assistant."""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.db_adapter import get_db


async def list_recommendations(params: dict[str, Any]) -> dict[str, Any]:
    """List active rightsizing recommendations, optionally filtered."""
    recs = get_db().get_recommendations(
        entity_id=params.get("entity_id") or None,
        category=params.get("category") or None,
        severity=params.get("severity") or None,
        active_only=bool(params.get("active_only", True)),
    )
    return {"count": len(recs), "recommendations": recs}


async def summary(params: dict[str, Any]) -> dict[str, Any]:
    """Counts of open recommendations by severity and category."""
    return get_db().get_recommendation_summary()


async def entity_history(params: dict[str, Any]) -> dict[str, Any]:
    """Recent resource-history samples for one entity."""
    samples = get_db().get_resource_history(
        str(params.get("entity_id", "")),
        limit=int(params.get("limit", 100)),
    )
    return {"count": len(samples), "samples": samples}


async def resource_aggregate(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregated CPU/memory/disk statistics for one entity."""
    return get_db().get_resource_history_aggregate(str(params.get("entity_id", "")))
