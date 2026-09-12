"""PVE2Audit - Resource analysis and rightsizing recommendations."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None
from PVE2Services.core.wiki_service.app.proxmox_adapter import (
    create_client_if_possible,
)
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.libs.plugin_base import get_core_machine

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .analyzer import Analyzer
from .collector import Collector
from .frontend import build_page
from .schemas import AuditConfig, RecommendationOut, SummaryReport

logger = logging.getLogger("pve2audit")


async def _core_machine_specs() -> dict:
    """Map audit entity ids to {name, cores} from PVE2Core's cache."""
    specs: dict = {}
    try:
        from PVE2Services.plugins import PVE2Core as core_plugin

        cache = getattr(core_plugin, "_cache", None)
        if cache is not None:
            for m in await cache.get_all():
                prefix = "vm-" if m.type == "vm" else "lxc-"
                specs[f"{prefix}{m.id}"] = {"name": m.name, "cores": m.cores or 1}
    except Exception as e:
        logger.warning("Could not read PVE2Core cache for entity specs: %s", e)
    return specs


def _build_config(config: dict) -> AuditConfig:
    return AuditConfig(**config)


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        config_manager = ConnectorConfig()
    connector_id = "pve2audit"

    def _auto_collect_job():
        """Background sampling: one resource_history row per machine per tick.

        Rightsizing needs history — without regular sampling there is nothing
        to take a median over. Runs every collect_interval_minutes (from the
        audit config); the scheduler's leader lease keeps replicas from
        double-collecting. Prunes samples past the 30-day retention horizon.
        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            db = DBAdapter()
            client = loop.run_until_complete(create_client_if_possible(None, None, None))
            if not client:
                return
            try:
                collector = Collector(db, pve=client)
                result = loop.run_until_complete(collector.run(timeframe="hour"))
                pruned = db.prune_resource_history(days=30)
                logger.info("Auto-collect: %s samples, pruned %s old rows", result.get("collected"), pruned)
                if audit:
                    try:
                        audit.log(connector_id, "OK", "Auto-collect completed",
                                  detail=f"samples_collected: {result.get('collected', 0)}\n"
                                         f"samples_pruned: {pruned}")
                    except Exception:
                        pass
            finally:
                loop.run_until_complete(client.close())
        except Exception:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Auto-collect failed",
                              detail="Background audit collection failed")
                except Exception:
                    pass
            logger.exception("Background audit collection failed")
        finally:
            loop.close()

    try:
        from PVE2Services.libs.scheduler import add_job

        interval = 30
        if config_manager:
            interval = int(config_manager.get_config(connector_id).get("collect_interval_minutes", 30) or 30)
        add_job("pve2audit_collect", _auto_collect_job, seconds=max(5, interval) * 60)
    except Exception:
        logger.exception("Could not register the audit auto-collector job")

    @app.get("/api/plugins/pve2audit/info")
    async def plugin_info():
        return {
            "plugin": "pve2audit",
            "name": "PVE2 Audit",
            "version": "0.1.0",
            "description": "Resource utilization analysis and rightsizing recommendations",
            "status": "active",
        }

    @app.get("/api/plugins/pve2audit/config")
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

    @app.post("/api/plugins/pve2audit/config")
    async def save_config(body: AuditConfig):
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

    @app.post("/api/plugins/pve2audit/test")
    async def test_connection():
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        base = config.get("proxmox_url")
        if not base:
            return {"connected": False, "error": "Proxmox URL not configured"}
        try:
            client = await create_client_if_possible(base, config.get("proxmox_token"), config.get("proxmox_secret"))
            if not client:
                return {"connected": False, "error": "Could not create Proxmox client"}
            nodes = await client.get_nodes()
            await client.close()
            return {"connected": True, "nodes": len(nodes)}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    @app.post("/api/plugins/pve2audit/sync")
    async def trigger_sync(timeframe: str = Query("hour", pattern="^(hour|day|week|month|year)$")):
        # No "enabled" gate here: audit has no external connection of its own —
        # it analyzes PVE2Core data via the global Proxmox settings.
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)

        db = DBAdapter()
        base = config.get("proxmox_url")
        client = await create_client_if_possible(
            base, config.get("proxmox_token"), config.get("proxmox_secret")
        )
        if not client:
            return {"error": "Could not create Proxmox client"}

        try:
            collector = Collector(db, pve=client)
            collect_result = await collector.run(timeframe=timeframe)

            thresholds = config.get("thresholds", {})
            window = config.get("analysis_window_days", 7)
            analyzer = Analyzer(db, thresholds=thresholds, entity_names=await _core_machine_specs())
            analysis_result = analyzer.run(window_days=window)

            # Keep the sample table at the retention horizon
            pruned = db.prune_resource_history(days=30)

            config_manager.update_sync_state(
                connector_id, "success",
                items_synced=collect_result.get("collected", 0),
            )
            if audit:
                try:
                    audit.log(connector_id, "OK", "Audit sync completed",
                              detail=f"timeframe: {timeframe}\n"
                                     f"samples_collected: {collect_result.get('collected', 0)}\n"
                                     f"recommendations: {analysis_result.get('recommendations', 0) if isinstance(analysis_result, dict) else 'n/a'}\n"
                                     f"samples_pruned: {pruned}")
                except Exception:
                    pass
            return {
                "status": "success",
                "collector": collect_result,
                "pruned_samples": pruned,
                "analyzer": analysis_result,
            }
        except Exception as e:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Audit sync failed",
                              detail=f"error: {e}")
                except Exception:
                    pass
            logger.exception("Sync failed: %s", e)
            if config_manager:
                config_manager.update_sync_state(connector_id, "error", error=str(e))
            return {"status": "error", "error": str(e)}
        finally:
            await client.close()

    @app.get("/api/plugins/pve2audit/recommendations", response_model=list[RecommendationOut])
    async def list_recommendations(
        entity_id: str = Query(None),
        category: str = Query(None, pattern="^(cpu|memory|disk|idle|node_balance|drift)$"),
        severity: str = Query(None, pattern="^(info|warning|critical)$"),
        active_only: bool = Query(True),
    ):
        db = DBAdapter()
        recs = db.get_recommendations(
            entity_id=entity_id, category=category,
            severity=severity, active_only=active_only,
        )
        # Attach per-entity data coverage so the UI can warn when history is
        # too short to trust (median over < 7 days is preliminary).
        coverage = db.get_resource_history_coverage()
        now = datetime.now(timezone.utc)
        out = []
        for r in recs:
            item = dict(r)
            cov = coverage.get(r.get("entity_id"))
            if cov and cov.get("first_seen"):
                first = cov["first_seen"]
                if isinstance(first, str):
                    # SQLite returns timestamps as strings (naive UTC)
                    first = datetime.fromisoformat(first).replace(tzinfo=timezone.utc)
                elif first.tzinfo is None:
                    first = first.replace(tzinfo=timezone.utc)
                item["data_days"] = round((now - first).total_seconds() / 86400, 1)
                item["sample_count"] = cov["samples"]
            else:
                item["data_days"] = None
                item["sample_count"] = 0
            out.append(item)
        return out

    @app.get("/api/plugins/pve2audit/recommendations/{rec_id}", response_model=RecommendationOut)
    async def get_recommendation(rec_id: int):
        db = DBAdapter()
        recs = db.get_recommendations(active_only=False)
        for r in recs:
            if r["id"] == rec_id:
                return r
        raise HTTPException(status_code=404, detail="Recommendation not found")

    @app.post("/api/plugins/pve2audit/recommendations/{rec_id}/apply")
    async def apply_recommendation(rec_id: int):
        """Execute a rightsizing suggestion against Proxmox.

        CPU and memory advice are applied for real (PUT .../config). Disk
        advice stays bookkeeping-only: Proxmox cannot shrink disks and the
        advice carries no target size, so growing is a judgment call made in
        the Proxmox UI. Requires VM.Config.CPU / VM.Config.Memory privileges
        on the token; on running machines without hotplug the change takes
        effect at the next start.
        """
        import re as _re

        db = DBAdapter()
        recs = db.get_recommendations(active_only=False)
        rec = next((r for r in recs if r["id"] == rec_id), None)
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if rec.get("applied"):
            return {"status": "ok", "message": "Already applied", "applied": True}

        category = rec.get("category", "")
        if category not in ("cpu", "memory"):
            return {"status": "manual", "message": "Disk/idle advice cannot be applied automatically — handle it in Proxmox", "applied": True}

        machine = await get_core_machine(rec.get("entity_id", "").split("-", 1)[-1])
        if not machine:
            return {"status": "error", "message": "Machine not found in PVE2Core cache — run a Core sync"}
        node, pve_type = machine.get("node"), machine.get("type")
        if not node or pve_type not in ("vm", "lxc"):
            return {"status": "error", "message": "Invalid machine data"}

        suggested = rec.get("suggested_value", "")
        params: dict = {}
        if category == "cpu":
            m = _re.search(r"(\d+)\s*vCPU", suggested or "")
            if not m:
                return {"status": "error", "message": f"Cannot parse suggested value: {suggested!r}"}
            params["cores"] = int(m.group(1))
        else:
            m = _re.search(r"(\d+)\s*GB", suggested or "")
            if not m:
                return {"status": "error", "message": f"Cannot parse suggested value: {suggested!r}"}
            params["memory"] = int(m.group(1)) * 1024  # MB

        client = await create_client_if_possible(None, None, None)
        if not client:
            return {"status": "error", "message": "No Proxmox connection — configure PVE2 Core"}
        try:
            await client.set_machine_config(node, str(machine.get("id")), pve_type, params)
        except RuntimeError as e:
            msg = str(e)
            if "403" in msg:
                return {"status": "error", "message": "Token lacks VM.Config.CPU/VM.Config.Memory privileges — grant them in Proxmox (Datacenter → Permissions)"}
            return {"status": "error", "message": f"Proxmox rejected the change: {msg[:200]}"}
        except Exception as e:
            return {"status": "error", "message": f"Apply failed: {e}"}
        finally:
            await client.close()

        db.mark_recommendation_applied(rec_id)
        effect = "applied live" if machine.get("status") == "stopped" else "saved — effective live with hotplug, otherwise at next start"
        if audit:
            try:
                audit.log(connector_id, "CRITICAL", "Recommendation applied",
                          detail=f"rec_id: {rec_id}\n"
                                 f"entity: {rec.get('entity_id', '')}\n"
                                 f"category: {category}\n"
                                 f"suggested: {suggested}\n"
                                 f"applied: {effect}")
            except Exception:
                pass
        return {"status": "ok", "message": f"{category} set to {suggested} on {machine.get('name')} ({effect})", "applied": True}

    @app.patch("/api/plugins/pve2audit/recommendations/{rec_id}")
    async def update_recommendation(rec_id: int, action: str = Query(..., pattern="^(dismiss|applied)$")):
        db = DBAdapter()
        ok = (
            db.dismiss_recommendation(rec_id)
            if action == "dismiss"
            else db.mark_recommendation_applied(rec_id)
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if audit:
            try:
                audit.log(connector_id, "INFO", f"Recommendation {action}",
                          detail=f"rec_id: {rec_id}")
            except Exception:
                pass
        return {"status": "ok", "id": rec_id, "action": action}

    @app.get("/api/plugins/pve2audit/report/summary", response_model=SummaryReport)
    async def report_summary():
        db = DBAdapter()
        return db.get_recommendation_summary()

    @app.get("/api/plugins/pve2audit/report/nodes")
    async def report_nodes():
        db = DBAdapter()
        since = datetime.now(timezone.utc)
        cutoff = since - timedelta(days=1)
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""SELECT
                    node, entity_type,
                    COUNT(DISTINCT entity_id) as total,
                    AVG(cpu_avg) as avg_cpu,
                    AVG(CAST(mem_used AS REAL) / NULLIF(mem_max, 1)) as avg_mem_pct
                FROM resource_history
                WHERE timestamp >= :cutoff
                GROUP BY node, entity_type"""),
                {"cutoff": cutoff},
            ).fetchall()
        nodes: dict = {}
        for r in rows:
            d = dict(r._mapping)
            n = d["node"]
            if n not in nodes:
                nodes[n] = {"node": n, "total_vms": 0, "total_lxcs": 0, "avg_cpu": 0, "avg_mem_pct": 0}
            if d["entity_type"] == "vm":
                nodes[n]["total_vms"] = d["total"]
            else:
                nodes[n]["total_lxcs"] = d["total"]
            nodes[n]["avg_cpu"] = max(nodes[n]["avg_cpu"], d["avg_cpu"] or 0)
            nodes[n]["avg_mem_pct"] = max(nodes[n]["avg_mem_pct"], d["avg_mem_pct"] or 0)
        return {"nodes": list(nodes.values())}

    @app.get("/api/plugins/pve2audit/history/{entity_id}")
    async def entity_history(entity_id: str, days: int = Query(7, ge=1, le=90)):
        db = DBAdapter()
        from datetime import timedelta
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = db.get_resource_history(entity_id, since=since, limit=2000)
        return {
            "entity_id": entity_id,
            "samples": [
                {
                    "timestamp": r["timestamp"].isoformat() if hasattr(r["timestamp"], "isoformat") else r["timestamp"],
                    "cpu_avg": r["cpu_avg"],
                    "mem_used": r["mem_used"],
                    "mem_max": r["mem_max"],
                    "disk_used": r["disk_used"],
                    "disk_max": r["disk_max"],
                }
                for r in rows
            ],
        }

    @app.get("/admin/pve2audit", response_class=HTMLResponse)
    async def admin_page():
        return HTMLResponse(content=build_page())
