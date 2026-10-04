"""PVE2DNS — DNS synchronization connector with Pi-hole and AdGuard support."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.libs.plugin_base import get_core_machines

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .frontend import build_page
from .providers import create_providers
from .schemas import DNSConfig, DNSRecordIn, DNSRecordOut, SyncResult

logger = logging.getLogger("pve2dns")


def _sanitise_hostname(name: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower()).strip("-")


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        config_manager = ConnectorConfig()
    connector_id = "pve2dns"

    @app.get("/api/plugins/pve2dns/info")
    async def plugin_info():
        return {
            "plugin": "pve2dns",
            "name": "PVE2 DNS",
            "version": "0.1.0",
            "description": "Sync Proxmox machines to Pi-hole / AdGuard DNS",
            "status": "active",
        }

    @app.get("/api/plugins/pve2dns/config")
    async def get_config():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        sync_state = config_manager.get_sync_state(connector_id)
        return {"configured": bool(config.get("domain")), "config": config, "sync_state": sync_state}

    @app.post("/api/plugins/pve2dns/config")
    async def save_config(body: DNSConfig):
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

    @app.post("/api/plugins/pve2dns/test")
    async def test_connection():
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        if not config.get("domain"):
            return {"connected": False, "error": "Domain not configured"}
        providers = create_providers(config)
        if not providers:
            return {"connected": False, "error": "No DNS providers enabled"}
        results = {}
        all_ok = True
        try:
            for p in providers:
                name = type(p).__name__.replace("Provider", "").lower()
                r = await p.test_connection()
                results[name] = r
                if not r.get("connected"):
                    all_ok = False
        finally:
            for p in providers:
                try:
                    await p.close()
                except Exception:  # noqa: BLE001 — teardown is best-effort
                    pass
        return {"connected": all_ok, "results": results}

    @app.post("/api/plugins/pve2dns/sync", response_model=SyncResult)
    async def trigger_sync():
        if not config_manager:
            return SyncResult(status="error", errors=["Config manager unavailable"])
        config = config_manager.get_config(connector_id)
        if not config.get("enabled"):
            return SyncResult(status="error", errors=["Connector not enabled"])
        if not config.get("domain"):
            return SyncResult(status="error", errors=["Domain not configured"])

        db = DBAdapter()
        records = db.get_dns_records()
        enabled = [r for r in records if r.get("enabled")]
        # Disabled records that were previously pushed must be removed from DNS
        stale = [r for r in records if not r.get("enabled") and r.get("last_synced")]
        if not enabled and not stale:
            return SyncResult(status="success", records_synced=0)

        domain = config["domain"].lstrip(".")
        providers = create_providers(config)
        if not providers:
            return SyncResult(status="error", errors=["No DNS providers enabled"])

        def _fqdn(hostname: str) -> str:
            hostname = hostname.rstrip(".")
            if hostname.endswith("." + domain):
                return hostname
            return f"{hostname}.{domain}"

        all_errors: list[str] = []
        synced_ids: set[str] = set()
        deleted_ids: list[str] = []
        pihole_result = None
        adguard_result = None

        for p in providers:
            name = type(p).__name__.replace("Provider", "").lower()
            try:
                for r in stale:
                    try:
                        await p.delete_record(_fqdn(r["hostname"]), r["ip_address"])
                        deleted_ids.append(r["machine_id"])
                    except Exception as e:
                        all_errors.append(f"{name}: delete {r['hostname']}: {e}")
                payload = [
                    {"hostname": _fqdn(r["hostname"]), "ip": r["ip_address"]}
                    for r in enabled
                ]
                result = await p.bulk_sync(payload)
                if name == "pihole":
                    pihole_result = result
                elif name == "adguard":
                    adguard_result = result
                if result.get("errors"):
                    all_errors.extend(result["errors"])
                else:
                    # A record is synced once even when multiple resolvers are
                    # configured; the set avoids counting it per provider.
                    synced_ids.update(r["machine_id"] for r in enabled)
            except Exception as e:
                all_errors.append(f"{name}: {e}")
            finally:
                try:
                    await p.close()
                except Exception:  # noqa: BLE001 — teardown is best-effort
                    pass

        if synced_ids:
            db.mark_dns_record_synced(list(synced_ids))
        # Stale records were deleted — forget their sync state so we don't
        # retry deletion forever.
        if deleted_ids:
            db.clear_dns_record_synced(deleted_ids)

        status = "error" if all_errors and not synced_ids else "success"
        config_manager.update_sync_state(connector_id, status, items_synced=len(synced_ids))
        if audit:
            try:
                sev = "OK" if status == "success" else "WARNING"
                audit.log(connector_id, sev, "DNS sync completed",
                          detail=f"records_synced: {len(synced_ids)}\n"
                                 f"records_deleted: {len(deleted_ids)}\n"
                                 f"errors: {len(all_errors)}\n"
                                 f"domain: {domain}")
            except Exception:
                pass
        return SyncResult(
            status=status,
            pihole=pihole_result,
            adguard=adguard_result,
            records_synced=len(synced_ids),
            errors=all_errors,
        )

    @app.get("/api/plugins/pve2dns/records", response_model=list[DNSRecordOut])
    async def list_records():
        db = DBAdapter()
        return db.get_dns_records()

    @app.get("/api/plugins/pve2dns/records/{machine_id}", response_model=DNSRecordOut)
    async def get_record(machine_id: str):
        db = DBAdapter()
        rec = db.get_dns_record(machine_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Record not found")
        return rec

    @app.put("/api/plugins/pve2dns/records/{machine_id}", response_model=dict)
    async def save_record(machine_id: str, body: DNSRecordIn):
        db = DBAdapter()
        ok = db.save_dns_record(
            machine_id=body.machine_id,
            machine_name=body.machine_name,
            hostname=body.hostname,
            ip_address=body.ip_address,
            enabled=body.enabled,
        )
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to save record")
        return {"status": "ok", "machine_id": machine_id}

    @app.post("/api/plugins/pve2dns/records/bulk", response_model=dict)
    async def bulk_save(records: list[DNSRecordIn]):
        db = DBAdapter()
        saved = db.bulk_save_dns_records([r.model_dump() for r in records])
        if audit:
            try:
                hostnames = [r.hostname for r in records]
                audit.log(connector_id, "INFO", "DNS records bulk saved",
                          detail=f"count: {saved}\n"
                                 f"hostnames: {', '.join(hostnames[:5])}"
                                 + (f" ... +{len(hostnames)-5}" if len(hostnames) > 5 else ""))
            except Exception:
                pass
        return {"status": "ok", "saved": saved}

    @app.delete("/api/plugins/pve2dns/records/{machine_id}")
    async def delete_record(machine_id: str):
        db = DBAdapter()
        ok = db.delete_dns_record(machine_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Record not found")
        if audit:
            try:
                audit.log(connector_id, "INFO", "DNS record deleted",
                          detail=f"machine_id: {machine_id}")
            except Exception:
                pass
        return {"status": "deleted", "machine_id": machine_id}

    @app.get("/api/plugins/pve2dns/machines")
    async def list_machines_with_dns():
        """Return machines from PVE2Core merged with saved DNS records."""
        db = DBAdapter()
        records = {r["machine_id"]: r for r in db.get_dns_records()}
        machines = await get_core_machines()

        result = []
        for m in machines:
            mid = str(m.get("id", ""))
            saved = records.get(mid)
            ips = m.get("ip_addresses", [])
            result.append({
                "machine_id": mid,
                "machine_name": m.get("name", ""),
                "type": m.get("type", ""),
                "node": m.get("node", ""),
                "status": m.get("status", ""),
                "ip_address": saved["ip_address"] if saved else (ips[0] if ips else ""),
                "hostname": saved["hostname"] if saved else _sanitise_hostname(m.get("name", f"vm-{mid}")),
                "domain": "",
                "dns_enabled": saved["enabled"] if saved else False,
                "last_synced": saved.get("last_synced") if saved else None,
            })
        return {"machines": result, "total": len(result)}

    @app.get("/admin/pve2dns", response_class=HTMLResponse)
    async def admin_page():
        configured = False
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            configured = bool(cfg.get("domain"))
        return HTMLResponse(content=build_page(configured=configured))
