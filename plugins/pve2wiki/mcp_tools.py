"""Read-only MCP tools exposed by PVE2 Wiki to the Winky assistant."""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.db_adapter import get_db


async def list_pages(params: dict[str, Any]) -> dict[str, Any]:
    """List synced Wiki.js pages."""
    pages = get_db().get_wiki_pages()
    return {"count": len(pages), "pages": pages}


async def get_page(params: dict[str, Any]) -> dict[str, Any]:
    """Return one synced wiki page by entity id."""
    page = get_db().get_wiki_page(str(params.get("entity_id", "")))
    return {"found": page is not None, "page": page}


async def list_sync_state(params: dict[str, Any]) -> dict[str, Any]:
    """List the sync-state entries (entities tracked by the sync engine)."""
    states = get_db().get_sync_state(limit=int(params.get("limit", 100)))
    return {"count": len(states), "states": states}
