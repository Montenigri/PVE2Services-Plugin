"""PVE2Drift — detect drift between OpenTofu declared state and the live cluster.

The system proposes, the administrator decides: this plugin never manages
resources, it observes and reports misalignments.

- Ingestion: POST /api/v1/state/ingest (API key, payload = `tofu show -json`)
- Matching: unique tag injected by the IaC module, joined against the live
  tags the Core Agent already collects (vmid is an attribute, not the key)
- Check: scheduled job comparing the last ingested declared_state with live
- Lifecycle: drift events open on transition, close on realignment
"""

import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .engine import (
    DEFAULT_TRACKED_FIELDS,
    PLUGIN_ID,
    resolve_on_ingestion,
    run_drift_check,
)
from .frontend import build_page
from .matcher import build_live_index, matching_tag_for
from .parser import StateParseError, parse_tofu_state
from .schemas import ApiKeyCreate, DriftConfig, IngestResult

logger = logging.getLogger("pve2drift")

INGEST_PATH = "/api/v1/state/ingest"


def _extract_api_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-pve2-api-key", "").strip()


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        try:
            config_manager = ConnectorConfig()
        except Exception:
            logger.warning("ConnectorConfig unavailable")
    connector_id = PLUGIN_ID

    def _cfg() -> dict:
        if not config_manager:
            return {}
        cfg = config_manager.get_config(connector_id)
        return cfg if isinstance(cfg, dict) else {}

    @app.get(f"/api/plugins/{connector_id}/info")
    async def plugin_info():
        return {
            "plugin": connector_id,
            "name": "PVE2 Drift",
            "version": "0.1.0",
            "description": "Detect drift between OpenTofu declared state and the live Proxmox cluster",
            "status": "active",
        }

    @app.get(f"/api/plugins/{connector_id}/config")
    async def get_config():
        if not config_manager:
            return {"configured": False, "config": {}, "error": "Config manager unavailable"}
        config = _cfg()
        sync_state = config_manager.get_sync_state(connector_id)
        return {"configured": bool(config.get("enabled")), "config": config, "sync_state": sync_state}

    @app.post(f"/api/plugins/{connector_id}/config")
    async def save_config(body: DriftConfig):
        if not config_manager:
            raise HTTPException(status_code=503, detail="Config manager unavailable")
        success = config_manager.save_config(connector_id, body.model_dump(), body.enabled)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Config saved",
                          detail=f"enabled: {body.enabled}\n"
                                 f"check_interval_seconds: {body.check_interval_seconds}\n"
                                 f"tracked_fields: {', '.join(body.tracked_fields)}")
            except Exception:
                pass
        return {"saved": success, "connector": connector_id}

    @app.post(f"/api/plugins/{connector_id}/test")
    async def test_connection():
        from PVE2Services.libs.db_adapter import DBAdapter

        from .engine import core_status

        try:
            health = await core_status()
        except Exception as e:
            return {"connected": False, "error": str(e)}
        db = DBAdapter()
        keys = [k for k in db.list_api_keys() if not k.get("revoked")]
        return {
            "connected": bool(health.get("proxmox_connected")),
            "live_machines": health.get("cache_size", 0),
            "api_keys": len(keys),
            "ingested_resources": len(db.get_managed_resources()),
        }

    @app.post(f"/api/plugins/{connector_id}/sync")
    async def trigger_sync():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = _cfg()
        if not config.get("enabled"):
            if audit:
                try:
                    audit.log(connector_id, "WARNING", "Sync skipped",
                              detail="Plugin not enabled")
                except Exception:
                    pass
            return {"error": "Plugin not enabled"}
        result = await run_drift_check(
            tracked_fields=config.get("tracked_fields") or DEFAULT_TRACKED_FIELDS,
            unmanaged_to_audit=bool(config.get("unmanaged_to_audit", True)),
        )
        config_manager.update_sync_state(connector_id, "success", items_synced=result.checked)
        return result.model_dump()

    # --- Ingestion (push from CI, API-key auth instead of session) ---

    @app.post(INGEST_PATH, response_model=IngestResult)
    async def ingest_state(request: Request):
        from PVE2Services.libs.db_adapter import DBAdapter

        key = _extract_api_key(request)
        if not key:
            raise HTTPException(status_code=401, detail="Missing drift ingestion API key")
        db = DBAdapter()
        key_row = db.verify_api_key(key)
        if not key_row:
            raise HTTPException(status_code=401, detail="Invalid or revoked drift ingestion API key")
        try:
            payload = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail="Body must be valid JSON") from e
        try:
            resources, skipped = parse_tofu_state(payload)
        except StateParseError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        by_tag, _ = await build_live_index()
        resolved_total = 0
        for r in resources:
            tag = matching_tag_for(r.resource_address)
            declared = r.model_dump()
            rid = db.upsert_managed_resource(
                resource_address=r.resource_address,
                resource_type=r.resource_type,
                provider=r.provider,
                matching_tag=tag,
                last_vmid=r.vmid,
                cluster_id=str(key_row.get("environment", "default")),
                node=r.node,
                declared_state=json.dumps(declared),
            )
            resource_row = db.get_managed_resource(rid)
            if resource_row:
                resolved_total += resolve_on_ingestion(db, resource_row, declared, by_tag)

        if audit:
            try:
                audit.log(connector_id, "INFO", "State ingested",
                          detail=f"environment: {key_row.get('environment')}\n"
                                 f"resources: {len(resources)}\n"
                                 f"skipped_types: {skipped}\n"
                                 f"resolved_drifts: {resolved_total}")
            except Exception:
                pass
        return IngestResult(ingested=len(resources), resolved=resolved_total, skipped_types=skipped)

    # --- Introspection ---

    @app.get(f"/api/plugins/{connector_id}/resources")
    async def list_resources():
        from PVE2Services.libs.db_adapter import DBAdapter

        db = DBAdapter()
        open_by_resource: dict = {}
        for d in db.get_open_drifts():
            open_by_resource.setdefault(d["resource_id"], []).append({
                "field": d.get("field"), "declared_value": d.get("declared_value"),
                "live_value": d.get("live_value"), "category": d.get("category"),
                "first_detected_at": str(d.get("first_detected_at")),
            })
        out = []
        for r in db.get_managed_resources():
            declared = {}
            try:
                declared = json.loads(r.get("declared_state") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            out.append({
                "id": r.get("id"),
                "resource_address": r.get("resource_address"),
                "resource_type": r.get("resource_type"),
                "provider": r.get("provider"),
                "matching_tag": r.get("matching_tag"),
                "last_vmid": r.get("last_vmid"),
                "node": r.get("node"),
                "cluster_id": r.get("cluster_id"),
                "declared": declared,
                "last_ingested_at": str(r.get("last_ingested_at") or "") or None,
                "last_checked_at": str(r.get("last_checked_at") or "") or None,
                "open_drifts": open_by_resource.get(r.get("id"), []),
            })
        return {"resources": out, "total": len(out)}

    @app.get(f"/api/plugins/{connector_id}/drifts")
    async def list_drifts(
        status: str = Query(None, pattern="^(open|resolved)$"),
        limit: int = Query(200, ge=1, le=1000),
    ):
        from PVE2Services.libs.db_adapter import DBAdapter

        db = DBAdapter()
        events = db.get_drift_events(status=status, limit=limit)
        for e in events:
            for k in ("first_detected_at", "last_detected_at", "resolved_at"):
                e[k] = str(e[k]) if e.get(k) else None
        return {"events": events, "total": len(events)}

    # --- API key management (session-authed admin surface) ---

    @app.get(f"/api/plugins/{connector_id}/apikeys")
    async def list_api_keys():
        from PVE2Services.libs.db_adapter import DBAdapter

        return {"keys": DBAdapter().list_api_keys()}

    @app.post(f"/api/plugins/{connector_id}/apikeys")
    async def create_api_key(body: ApiKeyCreate):
        from PVE2Services.libs.db_adapter import DBAdapter

        plaintext = DBAdapter().create_api_key(body.environment)
        if audit:
            try:
                audit.log(connector_id, "INFO", "API key created",
                          detail=f"environment: {body.environment}")
            except Exception:
                pass
        return {"key": plaintext, "environment": body.environment,
                "note": "Store it now: it is shown only once (CI secret)."}

    @app.delete(f"/api/plugins/{connector_id}/apikeys/{{key_id}}")
    async def revoke_api_key(key_id: int):
        from PVE2Services.libs.db_adapter import DBAdapter

        ok = DBAdapter().revoke_api_key(key_id)
        if ok and audit:
            try:
                audit.log(connector_id, "INFO", "API key revoked", detail=f"key_id: {key_id}")
            except Exception:
                pass
        if not ok:
            raise HTTPException(status_code=404, detail="API key not found")
        return {"revoked": True, "key_id": key_id}

    # --- Snippet generator ("il sistema propone") ---

    @app.get(f"/api/plugins/{connector_id}/tf-snippet")
    async def tf_snippet(address: str = Query(..., min_length=1)):
        tag = matching_tag_for(address)
        return {
            "address": address,
            "tag": tag,
            "hcl": f'tags = ["{tag}"]',
            "note": ("Add this tag to the resource so PVE2Drift can match it "
                     "against the live cluster."),
        }

    # --- Scheduler ---

    @app.get(f"/api/plugins/{connector_id}/scheduler/status")
    async def drift_scheduler_status():
        from PVE2Services.libs.scheduler import scheduler_status

        status = scheduler_status()
        job = next((j for j in status.get("jobs", []) if j["id"] == connector_id), None)
        return {"running": job is not None, "job": job}

    @app.post(f"/api/plugins/{connector_id}/scheduler/start")
    async def start_drift_scheduler(interval_seconds: int = 3600):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = _cfg()
        actual_interval = int(config.get("check_interval_seconds") or interval_seconds)

        def _job():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                cfg = config_manager.get_config(connector_id)
                if not cfg.get("enabled"):
                    return
                result = loop.run_until_complete(run_drift_check(
                    tracked_fields=cfg.get("tracked_fields") or DEFAULT_TRACKED_FIELDS,
                    unmanaged_to_audit=bool(cfg.get("unmanaged_to_audit", True)),
                ))
                config_manager.update_sync_state(
                    connector_id, "success", items_synced=result.checked
                )
            except Exception:
                logger.exception("Background drift check failed")
            finally:
                loop.close()

        from PVE2Services.libs.scheduler import add_job

        ok = add_job(connector_id, _job, seconds=actual_interval)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Drift scheduler started",
                          detail=f"interval_seconds: {actual_interval}")
            except Exception:
                pass
        return {"started": ok, "interval_seconds": actual_interval}

    @app.post(f"/api/plugins/{connector_id}/scheduler/stop")
    async def stop_drift_scheduler():
        from PVE2Services.libs.scheduler import remove_job

        ok = remove_job(connector_id)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Drift scheduler stopped")
            except Exception:
                pass
        return {"stopped": ok}

    @app.get(f"/admin/{connector_id}", response_class=HTMLResponse)
    async def admin_page():
        cfg = _cfg()
        return HTMLResponse(content=build_page(configured=bool(cfg.get("enabled"))))
