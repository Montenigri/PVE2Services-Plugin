"""PVE2Power — Schedule automatic startup/shutdown of VMs and LXC containers."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.libs.plugin_base import get_core_health, get_core_machines

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .frontend import build_page
from .scheduler import check_and_act, should_be_on
from .schemas import PowerConfig, PowerScheduleIn

logger = logging.getLogger("pve2power")


def _tz_offset(tz_str: str) -> int:
    """Parse a timezone string like 'Europe/Rome' -> offset in minutes from UTC.
    Falls back to 0 on any error.
    """
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_str)
        now = datetime.now(tz)
        offset = now.utcoffset()
        if offset is not None:
            return int(offset.total_seconds() // 60)
    except Exception:
        pass
    return 0


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        config_manager = ConnectorConfig()
    connector_id = "pve2power"

    @app.get("/api/plugins/pve2power/info")
    async def plugin_info():
        return {
            "plugin": "pve2power",
            "name": "PVE2 Power",
            "version": "0.1.0",
            "description": "Schedule automatic VM/LXC startup and shutdown",
            "status": "active",
        }

    @app.get("/api/plugins/pve2power/config")
    async def get_config():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        sync_state = config_manager.get_sync_state(connector_id)
        return {"configured": bool(config.get("timezone")), "config": config, "sync_state": sync_state}

    @app.post("/api/plugins/pve2power/config")
    async def save_config(body: PowerConfig):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        success = config_manager.save_config(connector_id, body.model_dump(), body.enabled)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Config saved",
                          detail=f"enabled={body.enabled}")
            except Exception:
                pass
        return {"saved": success, "connector": connector_id}

    @app.post("/api/plugins/pve2power/test")
    async def test_connection():
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        try:
            health = await get_core_health()
            if health.get("proxmox_connected"):
                return {"connected": True}
            return {"connected": False, "error": "PVE2Core cache empty — run PVE2Core sync"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    @app.post("/api/plugins/pve2power/sync")
    async def trigger_sync():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        if not config.get("enabled"):
            if audit:
                try:
                    audit.log(connector_id, "WARNING", "Sync skipped",
                              detail="Plugin not enabled")
                except Exception:
                    pass
            return {"error": "Plugin not enabled"}
        tz = config.get("timezone", "UTC")
        offset = _tz_offset(tz)
        result = await check_and_act(tz_offset=offset)
        actions = result.get("actions", [])
        errors = result.get("errors", [])
        config_manager.update_sync_state(
            connector_id, "success",
            items_synced=len(actions),
        )
        if audit:
            try:
                severity = "OK" if not errors else "WARNING"
                audit.log(connector_id, severity, "Power check completed",
                          detail=f"schedules_checked: {result.get('checked', 0)}\n"
                                 f"actions_taken: {len(actions)}\n"
                                 f"errors: {len(errors)}")
            except Exception:
                pass
        return {"status": "success", **result}

    @app.get("/api/plugins/pve2power/machines")
    async def list_machines_with_schedules():
        db = DBAdapter()
        schedules = {s["machine_id"]: s for s in db.get_power_schedules()}
        machines = await get_core_machines()

        tz = "UTC"
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            tz = cfg.get("timezone", "UTC")
        offset = _tz_offset(tz)
        now = datetime.now(timezone.utc)

        result = []
        for m in machines:
            mid = str(m.get("id", ""))
            saved = schedules.get(mid)
            expected = None
            if saved and saved.get("enabled"):
                expected = should_be_on(saved, now, offset)
            result.append({
                "machine_id": mid,
                "machine_name": m.get("name", ""),
                "type": m.get("type", ""),
                "node": m.get("node", ""),
                "status": m.get("status", ""),
                "should_be_on": expected,
                "schedule": saved,
            })
        return {"machines": result, "total": len(result)}

    @app.put("/api/plugins/pve2power/schedules/{machine_id}")
    async def save_schedule(machine_id: str, body: PowerScheduleIn):
        db = DBAdapter()
        db.save_power_schedule(
            machine_id=body.machine_id,
            machine_name=body.machine_name,
            enabled=body.enabled,
            weekday_start_time=body.weekday_start_time,
            weekday_stop_time=body.weekday_stop_time,
            weekend_start_time=body.weekend_start_time,
            weekend_stop_time=body.weekend_stop_time,
            monday=body.monday,
            tuesday=body.tuesday,
            wednesday=body.wednesday,
            thursday=body.thursday,
            friday=body.friday,
            saturday=body.saturday,
            sunday=body.sunday,
            force_stop_timeout=body.force_stop_timeout,
        )
        if audit:
            try:
                audit.log(connector_id, "INFO", "Power schedule saved",
                          detail=f"machine_id: {machine_id}\n"
                                 f"machine_name: {body.machine_name}\n"
                                 f"enabled: {body.enabled}\n"
                                 f"weekday: {body.weekday_start_time}-{body.weekday_stop_time}\n"
                                 f"weekend: {body.weekend_start_time}-{body.weekend_stop_time}")
            except Exception:
                pass
        return {"status": "ok", "machine_id": machine_id}

    @app.delete("/api/plugins/pve2power/schedules/{machine_id}")
    async def delete_schedule(machine_id: str):
        db = DBAdapter()
        db.delete_power_schedule(machine_id)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Power schedule deleted",
                          detail=f"machine_id: {machine_id}")
            except Exception:
                pass
        return {"status": "deleted", "machine_id": machine_id}

    @app.get("/api/plugins/pve2power/status")
    async def power_status():
        db = DBAdapter()
        schedules = db.get_power_schedules()
        enabled = [s for s in schedules if s.get("enabled")]
        now = datetime.now(timezone.utc)
        tz = "UTC"
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            tz = cfg.get("timezone", "UTC")
        offset = _tz_offset(tz)

        should_be_on_count = 0

        for s in enabled:
            if should_be_on(s, now, offset):
                should_be_on_count += 1

        return {
            "total_schedules": len(schedules),
            "enabled_schedules": len(enabled),
            "should_be_on": should_be_on_count,
            "last_action": next((s.get("last_action") for s in enabled if s.get("last_action")), None),
            "last_action_at": next((s.get("last_action_at") for s in enabled if s.get("last_action_at")), None),
        }

    @app.get("/api/plugins/pve2power/scheduler/status")
    async def power_scheduler_status():
        from PVE2Services.libs.scheduler import scheduler_status
        status = scheduler_status()
        job = next((j for j in status.get("jobs", []) if j["id"] == "pve2power"), None)
        return {"running": job is not None, "job": job}

    @app.post("/api/plugins/pve2power/scheduler/start")
    async def start_power_scheduler(interval_seconds: int = 300):
        if not config_manager:
            return {"error": "Config manager unavailable"}

        config = config_manager.get_config(connector_id)
        actual_interval = config.get("poll_interval_seconds", interval_seconds)

        def _job():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                cfg = config_manager.get_config(connector_id)
                if not cfg.get("enabled"):
                    return
                tz = cfg.get("timezone", "UTC")
                offset = _tz_offset(tz)
                result = loop.run_until_complete(check_and_act(tz_offset=offset))
                config_manager.update_sync_state(
                    connector_id, "success",
                    items_synced=len(result.get("actions", [])),
                )
            except Exception:
                logger.exception("Background power check failed")
            finally:
                loop.close()

        from PVE2Services.libs.scheduler import add_job
        ok = add_job("pve2power", _job, seconds=actual_interval)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Power scheduler started",
                          detail=f"interval_seconds: {actual_interval}")
            except Exception:
                pass
        return {"started": ok, "interval_seconds": actual_interval}

    @app.post("/api/plugins/pve2power/scheduler/stop")
    async def stop_power_scheduler():
        from PVE2Services.libs.scheduler import remove_job
        ok = remove_job("pve2power")
        if audit:
            try:
                audit.log(connector_id, "INFO", "Power scheduler stopped")
            except Exception:
                pass
        return {"stopped": ok}

    @app.get("/admin/pve2power", response_class=HTMLResponse)
    async def admin_page():
        configured = False
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            configured = bool(cfg.get("enabled"))
        return HTMLResponse(content=build_page(configured=configured))
