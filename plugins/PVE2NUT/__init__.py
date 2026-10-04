"""PVE2NUT — NUT (Network UPS Tools) dashboard: multi-server UPS monitoring,
history charts, status-change events (notified through PVE2Notify) and
instant commands."""

import asyncio
import logging
import threading
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig, decrypt_value, encrypt_value
except ImportError:
    ConnectorConfig = None
    encrypt_value = None
    decrypt_value = None

from PVE2Services.libs.db_adapter import DBAdapter

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .frontend import build_page
from .nut_client import NUTClient, NUTError
from .poller import find_serving_server, poll_servers, run_poll
from .schemas import NutConfig

logger = logging.getLogger("pve2nut")

PLUGIN_ID = "pve2nut"
MIN_INTERVAL = 15

# Last successful poll snapshot (in-memory; rebuilt on next poll after restart)
_cache: dict = {"at": 0.0, "devices": {}, "servers": []}
_cache_lock = threading.Lock()


def _cache_devices(devices: dict, servers: list) -> None:
    with _cache_lock:
        _cache["at"] = time.time()
        _cache["devices"] = devices
        _cache["servers"] = servers


def _cache_fresh(max_age: float) -> bool:
    with _cache_lock:
        return bool(_cache["devices"]) and (time.time() - _cache["at"]) < max_age


def _cache_snapshot() -> dict:
    with _cache_lock:
        return {"at": _cache["at"], "devices": dict(_cache["devices"]),
                "servers": list(_cache["servers"])}


def _encrypt_passwords(config: dict) -> dict:
    """Encrypt each server's password before persisting (SECRET_FIELDS does
    not cover nested list entries)."""
    if not encrypt_value:
        return config
    out = dict(config)
    out["servers"] = [
        {**s, "password": encrypt_value(s["password"]) if s.get("password") else ""}
        for s in config.get("servers", [])
    ]
    return out


def _decrypt_passwords(config: dict) -> dict:
    """Mirror of _encrypt_passwords for reads (API responses and NUT auth)."""
    if not decrypt_value:
        return config
    out = dict(config)
    out["servers"] = [
        {**s, "password": decrypt_value(s["password"]) if s.get("password") else ""}
        for s in config.get("servers", [])
    ]
    return out


def load_plugin(app: FastAPI):
    class _LazyConfigManager:
        """Per-call ConnectorConfig so requests always bind to the live DB resolution."""

        def __getattr__(self, name):
            if ConnectorConfig is None:
                raise RuntimeError("Config manager unavailable")
            return getattr(ConnectorConfig(), name)

        def __bool__(self):
            return ConnectorConfig is not None

    config_manager = _LazyConfigManager()
    connector_id = PLUGIN_ID

    def _get_config() -> dict:
        try:
            if not config_manager:
                return {}
            return _decrypt_passwords(config_manager.get_config(connector_id))
        except RuntimeError:
            return {}

    @app.get("/api/plugins/pve2nut/info")
    async def plugin_info():
        return {
            "plugin": PLUGIN_ID,
            "name": "PVE2 NUT",
            "version": "0.1.0",
            "description": "NUT (Network UPS Tools) dashboard — multi-server UPS monitoring",
            "status": "active",
        }

    @app.get("/api/plugins/pve2nut/config")
    async def get_config():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = _get_config()
        sync_state = config_manager.get_sync_state(connector_id)
        return {
            "configured": bool(config.get("enabled") and config.get("servers")),
            "config": config,
            "sync_state": sync_state,
        }

    @app.post("/api/plugins/pve2nut/config")
    async def save_config(body: NutConfig):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = _encrypt_passwords(body.model_dump())
        success = config_manager.save_config(connector_id, config, body.enabled)
        if audit:
            try:
                servers = [s.get("label") or s.get("host", "?") for s in body.servers]
                audit.log(connector_id, "INFO", "Config saved",
                          detail=f"enabled: {body.enabled}\n"
                                 f"servers ({len(servers)}): {', '.join(servers) or 'none'}")
            except Exception:
                pass
        return {"saved": success, "connector": connector_id}

    @app.post("/api/plugins/pve2nut/test")
    async def test_connection():
        config = _get_config()
        servers = [s for s in (config.get("servers") or []) if s.get("enabled", True)]
        if not servers:
            return {"tested": False, "error": "No NUT servers configured", "results": []}
        devices, server_results = await asyncio.to_thread(poll_servers, servers)
        return {"tested": all(r["ok"] for r in server_results),
                "devices_found": len(devices), "results": server_results}

    @app.post("/api/plugins/pve2nut/sync")
    async def trigger_sync():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = _get_config()
        if not config.get("enabled") or not config.get("servers"):
            if audit:
                try:
                    audit.log(connector_id, "WARNING", "Sync skipped",
                              detail="Plugin not enabled or no servers configured")
                except Exception:
                    pass
            return {"error": "Plugin not enabled or no servers configured"}
        result = await run_poll(config, DBAdapter())
        _cache_devices({d["name"]: d for d in result["devices"]}, result["servers"])
        status = "success" if not result["errors"] else "partial"
        config_manager.update_sync_state(
            connector_id, status, error="; ".join(result["errors"]) or None,
            items_synced=len(result["devices"]))
        if audit:
            try:
                severity = "OK" if not result["errors"] else "WARNING"
                event_types = [e["event_type"] for e in result["events"]]
                audit.log(connector_id, severity, "Poll completed",
                          detail=f"servers: {len(result['servers'])}\n"
                                 f"devices: {len(result['devices'])}\n"
                                 f"events: {', '.join(event_types) or 'none'}\n"
                                 f"notifications_sent: {result['notified']}\n"
                                 f"errors: {len(result['errors'])}")
            except Exception:
                pass
        return result

    @app.get("/api/plugins/pve2nut/devices")
    async def list_devices():
        config = _get_config()
        if not config.get("enabled") or not config.get("servers"):
            return {"devices": [], "servers": [], "polled_at": None,
                    "error": "Plugin not configured"}
        interval = max(MIN_INTERVAL, int(config.get("poll_interval_seconds", 60) or 60))
        if _cache_fresh(interval * 2):
            snap = _cache_snapshot()
            return {"devices": list(snap["devices"].values()),
                    "servers": snap["servers"],
                    "polled_at": snap["at"]}
        result = await run_poll(config, DBAdapter())
        _cache_devices({d["name"]: d for d in result["devices"]}, result["servers"])
        return {"devices": result["devices"], "servers": result["servers"],
                "polled_at": _cache_snapshot()["at"], "errors": result["errors"]}

    @app.get("/api/plugins/pve2nut/history/{ups_name}")
    async def ups_history(ups_name: str, hours: int = 24):
        db = DBAdapter()
        return {"ups_name": ups_name, "hours": hours,
                "readings": db.get_nut_history(ups_name, hours=hours)}

    @app.get("/api/plugins/pve2nut/events")
    async def ups_events(limit: int = 100):
        return {"events": DBAdapter().get_nut_events(limit=max(1, min(limit, 500)))}

    @app.get("/api/plugins/pve2nut/clients/{ups_name}")
    async def ups_clients(ups_name: str):
        config = _get_config()
        snap = _cache_snapshot()
        server = find_serving_server(config, snap["devices"], ups_name)
        if not server:
            return {"error": f"UPS '{ups_name}' not served by any configured server", "clients": []}
        try:
            with NUTClient(server["host"], server.get("port", 3493),
                           username=server.get("username", ""),
                           password=server.get("password", "")) as client:
                return {"ups_name": ups_name,
                        "server": server.get("label") or server["host"],
                        "clients": client.list_clients(ups_name)}
        except NUTError as e:
            return {"error": str(e), "clients": []}

    @app.get("/api/plugins/pve2nut/commands/{ups_name}")
    async def ups_commands(ups_name: str):
        config = _get_config()
        snap = _cache_snapshot()
        server = find_serving_server(config, snap["devices"], ups_name)
        if not server:
            return {"error": f"UPS '{ups_name}' not served by any configured server", "commands": []}
        try:
            with NUTClient(server["host"], server.get("port", 3493),
                           username=server.get("username", ""),
                           password=server.get("password", "")) as client:
                return {"ups_name": ups_name, "commands": client.list_commands(ups_name)}
        except NUTError as e:
            return {"error": str(e), "commands": []}

    @app.post("/api/plugins/pve2nut/command/{ups_name}/{command}")
    async def run_ups_command(ups_name: str, command: str):
        if not config_manager:
            return {"executed": False, "error": "Config manager unavailable"}
        config = _get_config()
        snap = _cache_snapshot()
        server = find_serving_server(config, snap["devices"], ups_name)
        if not server:
            return {"executed": False, "error": f"UPS '{ups_name}' not served by any configured server"}
        try:
            with NUTClient(server["host"], server.get("port", 3493),
                           username=server.get("username", ""),
                           password=server.get("password", "")) as client:
                client.run_command(ups_name, command)
        except NUTError as e:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "UPS command failed",
                              detail=f"ups: {ups_name}\ncommand: {command}\nerror: {e}")
                except Exception:
                    pass
            return {"executed": False, "error": str(e)}
        if audit:
            try:
                audit.log(connector_id, "WARNING", "UPS command executed",
                          detail=f"ups: {ups_name}\ncommand: {command}\n"
                                 f"server: {server.get('label') or server['host']}")
            except Exception:
                pass
        return {"executed": True, "ups_name": ups_name, "command": command}

    @app.get("/api/plugins/pve2nut/scheduler/status")
    async def nut_scheduler_status():
        from PVE2Services.libs.scheduler import scheduler_status
        status = scheduler_status()
        job = next((j for j in status.get("jobs", []) if j["id"] == PLUGIN_ID), None)
        return {"running": job is not None, "job": job}

    @app.post("/api/plugins/pve2nut/scheduler/start")
    async def start_nut_scheduler():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = _get_config()
        interval = max(MIN_INTERVAL, int(config.get("poll_interval_seconds", 60) or 60))

        def _job():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                cfg = config_manager.get_config(connector_id)
                if not cfg.get("enabled"):
                    return
                result = loop.run_until_complete(run_poll(cfg, DBAdapter()))
                _cache_devices({d["name"]: d for d in result["devices"]}, result["servers"])
                status = "success" if not result["errors"] else "partial"
                config_manager.update_sync_state(
                    connector_id, status,
                    error="; ".join(result["errors"]) or None,
                    items_synced=len(result["devices"]))
            except Exception:
                logger.exception("Background NUT poll failed")
            finally:
                loop.close()

        from PVE2Services.libs.scheduler import add_job
        ok = add_job(PLUGIN_ID, _job, seconds=interval)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Poll scheduler started",
                          detail=f"interval_seconds: {interval}")
            except Exception:
                pass
        return {"started": ok, "interval_seconds": interval}

    @app.post("/api/plugins/pve2nut/scheduler/stop")
    async def stop_nut_scheduler():
        from PVE2Services.libs.scheduler import remove_job
        ok = remove_job(PLUGIN_ID)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Poll scheduler stopped")
            except Exception:
                pass
        return {"stopped": ok}

    @app.get("/admin/pve2nut", response_class=HTMLResponse)
    async def admin_page():
        configured = False
        if config_manager:
            cfg = _get_config()
            configured = bool(cfg.get("enabled") and cfg.get("servers"))
        return HTMLResponse(content=build_page(configured=configured))
