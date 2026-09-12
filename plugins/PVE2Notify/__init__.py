"""PVE2Notify — Monitor Proxmox state changes and send notifications."""

import asyncio
import json
import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .frontend import build_page
from .providers import create_providers
from .schemas import NotifyConfig, SyncResult, TestResult
from .watcher import (
    diff_snapshots,
    fetch_machines_from_core,
    load_snapshot,
)

logger = logging.getLogger("pve2notify")


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        config_manager = ConnectorConfig()
    connector_id = "pve2notify"

    @app.get("/api/plugins/pve2notify/info")
    async def plugin_info():
        return {
            "plugin": "pve2notify",
            "name": "PVE2 Notify",
            "version": "0.1.0",
            "description": "Send Proxmox state-change notifications to Discord, Slack, Mattermost, Telegram",
            "status": "active",
        }

    @app.get("/api/plugins/pve2notify/config")
    async def get_config():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        sync_state = config_manager.get_sync_state(connector_id)
        safe = {k: v for k, v in config.items() if not k.startswith("_")}
        return {"configured": bool(config.get("discord_webhook_url") or config.get("slack_webhook_url") or config.get("mattermost_webhook_url") or config.get("telegram_bot_token")), "config": safe, "sync_state": sync_state}

    @app.post("/api/plugins/pve2notify/config")
    async def save_config(body: NotifyConfig):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        existing = config_manager.get_config(connector_id)
        snapshot = existing.get("_snapshot", "{}")
        full = body.model_dump()
        full["_snapshot"] = snapshot
        success = config_manager.save_config(connector_id, full, body.enabled)
        if audit:
            try:
                providers_active = [k for k in ("discord_webhook_url", "slack_webhook_url",
                                    "mattermost_webhook_url", "telegram_bot_token")
                                    if full.get(k)]
                audit.log(connector_id, "INFO", "Config saved",
                          detail=f"enabled: {body.enabled}\nproviders: {', '.join(providers_active) or 'none'}")
            except Exception:
                pass
        return {"saved": success, "connector": connector_id}

    @app.post("/api/plugins/pve2notify/test")
    async def test_notifications():
        if not config_manager:
            return {"tested": False, "error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        providers = create_providers(config)
        if not providers:
            return {"tested": False, "error": "No notification providers enabled"}
        results = []
        all_ok = True
        for p in providers:
            name = type(p).__name__.replace("Provider", "").lower()
            try:
                r = await p.send_test()
                results.append({"provider": name, "success": r.get("success", False), "error": r.get("error", "")})
                if not r.get("success"):
                    all_ok = False
            except Exception as e:
                results.append({"provider": name, "success": False, "error": str(e)})
                all_ok = False
        return {"tested": all_ok, "results": results}

    @app.post("/api/plugins/pve2notify/sync", response_model=SyncResult)
    async def trigger_sync():
        if not config_manager:
            return SyncResult(status="error", errors=["Config manager unavailable"])
        config = config_manager.get_config(connector_id)
        if not config.get("enabled"):
            if audit:
                try:
                    audit.log(connector_id, "WARNING", "Sync skipped",
                              detail="Notifier not enabled")
                except Exception:
                    pass
            return SyncResult(status="error", errors=["Notifier not enabled"])

        providers = create_providers(config)
        if not providers:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Sync failed",
                              detail="No notification providers enabled")
                except Exception:
                    pass
            return SyncResult(status="error", errors=["No notification providers enabled"])

        previous = load_snapshot(config)
        machines = await fetch_machines_from_core()
        by_id = {m.get("id", ""): m for m in machines}
        current = {m.get("id", ""): m.get("status", "unknown") for m in machines}

        events = diff_snapshots(previous, current, by_id)
        if not events:
            if audit:
                try:
                    audit.log(connector_id, "OK", "Sync completed",
                              detail="No state changes detected")
                except Exception:
                    pass
            return SyncResult(status="success", events=[], notifications_sent=0)

        sent = 0
        all_errors = []
        provider_results = []
        notified_events = []

        for p in providers:
            name = type(p).__name__.replace("Provider", "").lower()
            ok_count = 0
            for ev in events:
                ev_type = ev["event_type"]
                if not config.get(f"notify_{ev_type}", True):
                    continue
                try:
                    ok = await p.send_event(ev_type, ev)
                    if ok:
                        ok_count += 1
                        notified_events.append(ev)
                    else:
                        all_errors.append(f"{name}: failed to send {ev_type} for {ev['machine_id']}")
                except Exception as e:
                    all_errors.append(f"{name}: {e}")
            provider_results.append(TestResult(provider=name, success=ok_count > 0 or not events, error=""))
            sent += ok_count

        config["_snapshot"] = json.dumps(current)
        config_manager.save_config(connector_id, config, config.get("enabled", False))
        config_manager.update_sync_state(connector_id, "success", items_synced=sent)

        if audit:
            try:
                event_summary = {}
                for ev in events:
                    et = ev.get("event_type", "unknown")
                    event_summary[et] = event_summary.get(et, 0) + 1
                ev_str = ", ".join(f"{k}: {v}" for k, v in event_summary.items())
                audit.log(connector_id, "OK", "Sync completed",
                          detail=f"events: {ev_str}\n"
                                 f"notifications_sent: {sent}\n"
                                 f"errors: {len(all_errors)}")
            except Exception:
                pass

        return SyncResult(
            status="success" if not all_errors else "partial",
            events=[e for e in notified_events],
            notifications_sent=sent,
            provider_results=provider_results,
            errors=all_errors,
        )

    @app.get("/api/plugins/pve2notify/events")
    async def list_events():
        if not config_manager:
            return {"events": []}
        sync_state = config_manager.get_sync_state(connector_id)
        return {
            "events": [],
            "last_sync": sync_state.get("last_sync_at"),
            "items_synced": sync_state.get("items_synced", 0),
        }

    @app.get("/api/plugins/pve2notify/scheduler/status")
    async def notify_scheduler_status():
        from PVE2Services.libs.scheduler import scheduler_status
        status = scheduler_status()
        job = next((j for j in status.get("jobs", []) if j["id"] == "pve2notify"), None)
        return {"running": job is not None, "job": job}

    @app.post("/api/plugins/pve2notify/scheduler/start")
    async def start_notify_scheduler(interval_seconds: int = 300):
        if not config_manager:
            return {"error": "Config manager unavailable"}

        def _job():
            try:
                asyncio.run(_do_notify_check())
            except Exception:
                logger.exception("Background notify check failed")

        async def _do_notify_check():
            config = config_manager.get_config(connector_id)
            if not config.get("enabled"):
                return

            from .providers import create_providers
            from .watcher import (
                diff_snapshots,
                fetch_machines_from_core,
                load_snapshot,
            )

            providers = create_providers(config)
            if not providers:
                return

            previous = load_snapshot(config)
            machines = await fetch_machines_from_core()
            by_id = {m.get("id", ""): m for m in machines}
            current = {m.get("id", ""): m.get("status", "unknown") for m in machines}
            events = diff_snapshots(previous, current, by_id)
            if not events:
                return

            sent = 0
            for p in providers:
                for ev in events:
                    try:
                        ok = await p.send_event(ev["event_type"], ev)
                        if ok:
                            sent += 1
                    except Exception:
                        pass

            config["_snapshot"] = json.dumps(current)
            config_manager.save_config(connector_id, config, config.get("enabled", False))
            config_manager.update_sync_state(connector_id, "success", items_synced=sent)

        from PVE2Services.libs.scheduler import add_job
        ok = add_job("pve2notify", _job, seconds=interval_seconds)
        return {"started": ok}

    @app.post("/api/plugins/pve2notify/scheduler/stop")
    async def stop_notify_scheduler():
        from PVE2Services.libs.scheduler import remove_job
        ok = remove_job("pve2notify")
        return {"stopped": ok}

    @app.get("/admin/pve2notify", response_class=HTMLResponse)
    async def admin_page():
        configured = False
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            configured = bool(cfg.get("discord_webhook_url") or cfg.get("slack_webhook_url") or cfg.get("mattermost_webhook_url") or cfg.get("telegram_bot_token"))
        return HTMLResponse(content=build_page(configured=configured))
