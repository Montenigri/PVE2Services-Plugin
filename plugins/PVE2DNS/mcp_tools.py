"""Read-only MCP tools exposed by PVE2 DNS to the Winky assistant."""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.db_adapter import get_db


async def list_records(params: dict[str, Any]) -> dict[str, Any]:
    """List every managed DNS record."""
    records = get_db().get_dns_records()
    return {"count": len(records), "records": records}


async def get_record(params: dict[str, Any]) -> dict[str, Any]:
    """Return one DNS record by machine id."""
    record = get_db().get_dns_record(str(params.get("machine_id", "")))
    return {"found": record is not None, "record": record}
