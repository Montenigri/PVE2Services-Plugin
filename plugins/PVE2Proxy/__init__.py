"""PVE2Proxy — Reverse proxy configuration generator with SSH deploy."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig, decrypt_value, encrypt_value
except ImportError:
    ConnectorConfig = None
    encrypt_value = None
    decrypt_value = None
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.libs.plugin_base import get_core_machines

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .deployer import deploy_config, ssh_test
from .frontend import build_page
from .providers import create_providers
from .schemas import DeployResult, ProxyConfig, ProxyMappingIn, ProxyMappingOut

logger = logging.getLogger("pve2proxy")


def _sanitise_hostname(name: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower()).strip("-")


def _decrypt_ssh_key(config: dict) -> dict:
    """Decrypt SSH key in config if encryption is available."""
    if decrypt_value and config.get("ssh_key"):
        config = dict(config)
        config["ssh_key"] = decrypt_value(config["ssh_key"])
    return config


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        config_manager = ConnectorConfig()
    connector_id = "pve2proxy"

    @app.get("/api/plugins/pve2proxy/info")
    async def plugin_info():
        return {
            "plugin": "pve2proxy",
            "name": "PVE2 Proxy",
            "version": "0.1.0",
            "description": "Genera e deploya configurazioni proxy inverso (Nginx / Traefik)",
            "status": "active",
        }

    @app.get("/api/plugins/pve2proxy/config")
    async def get_config():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        sync_state = config_manager.get_sync_state(connector_id)
        configured = bool(config.get("ssh_host")) and bool(config.get("base_domain"))
        return {"configured": configured, "config": config, "sync_state": sync_state}

    @app.post("/api/plugins/pve2proxy/config")
    async def save_config(body: ProxyConfig):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        data = body.model_dump()
        if encrypt_value and data.get("ssh_key"):
            data["ssh_key"] = encrypt_value(data["ssh_key"])
        success = config_manager.save_config(connector_id, data, body.enabled)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Proxy config saved",
                          detail=f"enabled: {body.enabled}\n"
                                 f"proxy_type: {body.proxy_type}\n"
                                 f"base_domain: {body.base_domain}\n"
                                 f"ssh_host: {body.ssh_host}")
            except Exception:
                pass
        return {"saved": success, "connector": connector_id}

    @app.post("/api/plugins/pve2proxy/test")
    async def test_connection():
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        config = _decrypt_ssh_key(config_manager.get_config(connector_id))
        if not config.get("ssh_host"):
            return {"connected": False, "error": "SSH host not configured"}

        provider = create_providers(config)
        ok, msg = await ssh_test(
            host=config["ssh_host"],
            port=config.get("ssh_port", 22),
            user=config.get("ssh_user", "root"),
            key=config.get("ssh_key", ""),
        )
        ptype_result = {"type": config.get("proxy_type", "nginx"), "ok": True}
        try:
            pv = provider
            test_mappings = [{"hostname": "test", "domain": config.get("base_domain", ""),
                              "ip_address": "127.0.0.1", "port": 80, "enabled": True}]
            pv.generate(test_mappings, config)
        except Exception as e:
            ptype_result = {"type": config.get("proxy_type", "nginx"), "ok": False, "error": str(e)}

        return {
            "connected": ok,
            "ssh": msg,
            "provider": ptype_result,
        }

    @app.get("/api/plugins/pve2proxy/machines")
    async def list_machines_with_proxy():
        db = DBAdapter()
        mappings = {r["machine_id"]: r for r in db.get_proxy_mappings()}
        machines = await get_core_machines()

        result = []
        for m in machines:
            mid = str(m.get("id", ""))
            saved = mappings.get(mid)
            ips = m.get("ip_addresses", [])
            result.append({
                "machine_id": mid,
                "machine_name": m.get("name", ""),
                "type": m.get("type", ""),
                "node": m.get("node", ""),
                "status": m.get("status", ""),
                "ip_address": saved["ip_address"] if saved else (ips[0] if ips else ""),
                "hostname": saved["hostname"] if saved else _sanitise_hostname(m.get("name", f"vm-{mid}")),
                "domain": saved["domain"] if saved else "",
                "port": saved["port"] if saved else 80,
                "websocket": bool(saved["websocket"]) if saved else False,
                "cache": bool(saved["cache"]) if saved else False,
                "rate_limit": saved["rate_limit"] if saved else 0,
                "ssl_enabled": bool(saved["ssl_enabled"]) if saved else False,
                "extra_directives": saved["extra_directives"] if saved else "",
                "proxy_enabled": bool(saved["enabled"]) if saved else False,
                "last_deployed": saved.get("last_deployed") if saved else None,
            })
        return {"machines": result, "total": len(result)}

    @app.get("/api/plugins/pve2proxy/mappings", response_model=list[ProxyMappingOut])
    async def list_mappings():
        db = DBAdapter()
        return db.get_proxy_mappings()

    @app.put("/api/plugins/pve2proxy/mappings/{machine_id}")
    async def save_mapping(machine_id: str, body: ProxyMappingIn):
        db = DBAdapter()
        ok = db.save_proxy_mapping(
            machine_id=body.machine_id,
            machine_name=body.machine_name,
            hostname=body.hostname,
            domain=body.domain,
            ip_address=body.ip_address,
            port=body.port,
            websocket=body.websocket,
            cache=body.cache,
            rate_limit=body.rate_limit,
            ssl_enabled=body.ssl_enabled,
            extra_directives=body.extra_directives,
            enabled=body.enabled,
        )
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to save mapping")
        if audit:
            try:
                audit.log(connector_id, "INFO", "Proxy mapping saved",
                          detail=f"machine_id: {machine_id}\n"
                                 f"hostname: {body.hostname}.{body.domain}\n"
                                 f"ip: {body.ip_address}\n"
                                 f"enabled: {body.enabled}")
            except Exception:
                pass
        return {"status": "ok", "machine_id": machine_id}

    @app.post("/api/plugins/pve2proxy/mappings/bulk")
    async def bulk_save(mappings: list[ProxyMappingIn]):
        db = DBAdapter()
        saved = 0
        for m in mappings:
            ok = db.save_proxy_mapping(
                machine_id=m.machine_id,
                machine_name=m.machine_name,
                hostname=m.hostname,
                domain=m.domain,
                ip_address=m.ip_address,
                port=m.port,
                websocket=m.websocket,
                cache=m.cache,
                rate_limit=m.rate_limit,
                ssl_enabled=m.ssl_enabled,
                extra_directives=m.extra_directives,
                enabled=m.enabled,
            )
            if ok:
                saved += 1
        if audit:
            try:
                audit.log(connector_id, "INFO", "Proxy mappings bulk saved",
                          detail=f"count: {saved}\n"
                                 f"total: {len(mappings)}")
            except Exception:
                pass
        return {"status": "ok", "saved": saved}

    @app.delete("/api/plugins/pve2proxy/mappings/{machine_id}")
    async def delete_mapping(machine_id: str):
        db = DBAdapter()
        ok = db.delete_proxy_mapping(machine_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Mapping not found")
        if audit:
            try:
                audit.log(connector_id, "INFO", "Proxy mapping deleted",
                          detail=f"machine_id: {machine_id}")
            except Exception:
                pass
        return {"status": "deleted", "machine_id": machine_id}

    @app.post("/api/plugins/pve2proxy/generate", response_model=DeployResult)
    async def preview_config():
        if not config_manager:
            return DeployResult(status="error", message="Config manager unavailable")
        config = config_manager.get_config(connector_id)
        if not config.get("base_domain"):
            return DeployResult(status="error", message="Domain not configured")
        db = DBAdapter()
        mappings = db.get_proxy_mappings()
        provider = create_providers(config)
        config_str = provider.generate(mappings, config)
        return DeployResult(
            status="success",
            config=config_str,
            provider=config.get("proxy_type", "nginx"),
        )

    @app.post("/api/plugins/pve2proxy/deploy", response_model=DeployResult)
    async def trigger_deploy():
        if not config_manager:
            return DeployResult(status="error", message="Config manager unavailable")
        config = _decrypt_ssh_key(config_manager.get_config(connector_id))
        if not config.get("enabled"):
            if audit:
                try:
                    audit.log(connector_id, "WARNING", "Deploy skipped",
                              detail="Connector not enabled")
                except Exception:
                    pass
            return DeployResult(status="error", message="Connector not enabled")
        if not config.get("ssh_host"):
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Deploy failed",
                              detail="SSH host not configured")
                except Exception:
                    pass
            return DeployResult(status="error", message="SSH host not configured")
        db = DBAdapter()
        mappings = db.get_proxy_mappings()
        if audit:
            try:
                audit.log(connector_id, "CRITICAL", "Deploy started",
                          detail=f"proxy_type: {config.get('proxy_type', 'nginx')}\n"
                                 f"ssh_host: {config.get('ssh_host')}\n"
                                 f"mappings: {len(mappings)}")
            except Exception:
                pass
        result = await deploy_config(config.get("proxy_type", "nginx"), config, mappings)
        if result["status"] == "success":
            enabled_ids = [m["machine_id"] for m in mappings if m.get("enabled")]
            db.mark_proxy_deployed(enabled_ids)
            if config_manager:
                config_manager.update_sync_state(connector_id, "success",
                                                 items_synced=len(enabled_ids))
            if audit:
                try:
                    audit.log(connector_id, "OK", "Deploy completed",
                              detail=f"mappings: {len(enabled_ids)}")
                except Exception:
                    pass
        else:
            if config_manager:
                config_manager.update_sync_state(connector_id, "error",
                                                 error=result.get("message", ""))
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Deploy failed",
                              detail=f"error: {result.get('message', '')}")
                except Exception:
                    pass
        return DeployResult(
            status=result.get("status", "error"),
            message=result.get("message", ""),
            config=result.get("config", ""),
            provider=config.get("proxy_type", "nginx"),
        )

    @app.get("/api/plugins/pve2proxy/sync")
    async def sync_status():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        sync_state = config_manager.get_sync_state(connector_id)
        db = DBAdapter()
        mappings = db.get_proxy_mappings()
        enabled = [m for m in mappings if m.get("enabled")]
        return {
            "total_mappings": len(mappings),
            "enabled": len(enabled),
            "sync_state": sync_state,
        }

    @app.get("/admin/pve2proxy", response_class=HTMLResponse)
    async def admin_page():
        configured = False
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            configured = bool(cfg.get("ssh_host")) and bool(cfg.get("base_domain"))
        return HTMLResponse(content=build_page(configured=configured))
