"""PVE2Dash - Lightweight read-only dashboard for Proxmox cluster health."""

import logging

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None

from PVE2Services.core.wiki_service.app.proxmox_adapter import (
    create_client_if_possible,
)

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .frontend import build_page
from .schemas import DashConfig, HistoryResponse, HistorySample

logger = logging.getLogger("pve2dash")


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        config_manager = ConnectorConfig()
    connector_id = "pve2dash"

    @app.get("/api/plugins/pve2dash/info")
    async def plugin_info():
        return {
            "plugin": "pve2dash",
            "name": "PVE2 Dash",
            "version": "0.1.0",
            "description": "Lightweight read-only dashboard for cluster health",
            "status": "active",
        }

    @app.get("/api/plugins/pve2dash/config")
    async def get_config():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        sync_state = config_manager.get_sync_state(connector_id)
        return {
            "configured": bool(config.get("proxmox_url")),
            "config": config,
            "sync_state": sync_state,
        }

    @app.post("/api/plugins/pve2dash/config")
    async def save_config(body: DashConfig):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        success = config_manager.save_config(connector_id, body.model_dump(), body.enabled)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Config saved",
                          detail=f"enabled: {body.enabled}")
            except Exception:
                pass
        return {"saved": success, "connector": connector_id}

    @app.post("/api/plugins/pve2dash/test")
    async def test_connection():
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        # Missing per-plugin config falls back to the global proxmox_* DB
        # settings inside create_client_if_possible.
        client = await create_client_if_possible(
            config.get("proxmox_url"), config.get("proxmox_token"), config.get("proxmox_secret")
        )
        if not client:
            return {"connected": False, "error": "Proxmox URL not configured"}
        try:
            nodes = await client.get_nodes()
            await client.close()
            return {"connected": True, "nodes": len(nodes)}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    @app.post("/api/plugins/pve2dash/sync")
    async def trigger_sync():
        return {"status": "success", "message": "PVE2Dash is read-only — sync not needed"}

    @app.get(
        "/api/plugins/pve2dash/history/{entity_id}",
        response_model=HistoryResponse,
    )
    async def entity_history(
        entity_id: str = Path(..., pattern=r"^\d+$"),
        node: str = Query(..., min_length=1),
        entity_type: str = Query("qemu", pattern=r"^(qemu|lxc)$"),
        timeframe: str = Query("day", pattern=r"^(hour|day|week|month|year)$"),
    ):
        if not config_manager:
            raise HTTPException(status_code=503, detail="Config manager unavailable")
        config = config_manager.get_config(connector_id)
        try:
            client = await create_client_if_possible(
                config.get("proxmox_url"), config.get("proxmox_token"), config.get("proxmox_secret")
            )
            if not client:
                raise HTTPException(status_code=503, detail="Proxmox not configured")

            data = await client.get_rrd_data(node, entity_id, entity_type, timeframe)
            await client.close()
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Failed to fetch RRD data for %s: %s", entity_id, e)
            raise HTTPException(status_code=502, detail=str(e)) from e

        samples = []
        for row in data or []:
            samples.append(HistorySample(
                timestamp=row.get("time", ""),
                cpu=float(row.get("cpu", 0) or 0),
                mem=float(row.get("mem", 0) or 0),
                mem_used=int(row.get("mem", 0) or 0),
                mem_max=int(row.get("maxmem", 0) or 0),
                disk=float(row.get("disk", 0) or 0),
                disk_used=int(row.get("disk", 0) or 0),
                disk_max=int(row.get("maxdisk", 0) or 0),
                netin=int(row.get("netin", 0) or 0),
                netout=int(row.get("netout", 0) or 0),
            ))

        return HistoryResponse(entity_id=entity_id, samples=samples, timeframe=timeframe)

    @app.get("/admin/pve2dash", response_class=HTMLResponse)
    async def admin_page():
        return HTMLResponse(content=build_page())
