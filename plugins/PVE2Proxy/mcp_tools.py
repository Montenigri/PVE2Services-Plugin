"""Read-only MCP tools exposed by PVE2 Proxy to the Winky assistant."""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.db_adapter import get_db


async def list_mappings(params: dict[str, Any]) -> dict[str, Any]:
    """List every generated reverse-proxy mapping."""
    mappings = get_db().get_proxy_mappings()
    return {"count": len(mappings), "mappings": mappings}


async def get_mapping(params: dict[str, Any]) -> dict[str, Any]:
    """Return one reverse-proxy mapping by machine id."""
    mapping = get_db().get_proxy_mapping(str(params.get("machine_id", "")))
    return {"found": mapping is not None, "mapping": mapping}
