"""PVE2 Core plugin - central connector for Proxmox data."""

import asyncio
import logging
import random

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None

from PVE2Services.core.wiki_service.app.proxmox_adapter import (
    ProxmoxClient,
    create_client_if_possible,
)
from PVE2Services.libs.config_adapter import ConfigAdapter

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .cache import MachineCache
from .collector import Collector
from .frontend import build_page
from .schemas import (
    ActionResponse,
    ClusterResponse,
    CoreConfig,
    CoreSetup,
    GenericMachine,
    HealthResponse,
    NodeInfo,
    StorageInfo,
)

logger = logging.getLogger("pve2core")

_cache = MachineCache()
_warm_lock = asyncio.Lock()


async def _sync_if_configured() -> dict:
    """Run a collector sync if pve2core has an enabled, configured connector."""
    if not ConnectorConfig:
        return {"skipped": "no config manager"}
    config = ConnectorConfig().get_config("pve2core")
    if not (config.get("enabled") and config.get("proxmox_url")):
        return {"skipped": "not configured"}
    client = await create_client_if_possible(
        config.get("proxmox_url"), config.get("proxmox_token"),
        config.get("proxmox_secret"), insecure=config.get("proxmox_insecure", True),
    )
    if not client:
        return {"skipped": "no client"}
    try:
        collector = Collector(_cache, pve=client)
        return await collector.run()
    finally:
        await client.close()


async def _ensure_cache_warmed() -> None:
    """Single-flight: if the cache is empty, run one sync before serving.

    Keeps every dependent plugin (DNS/Proxy/Power/Wiki/Notify/Audit/Dash)
    functional immediately after an app restart instead of showing 0 machines.
    """
    stats = await _cache.stats()
    if stats.get("total", 0) > 0:
        return
    async with _warm_lock:
        stats = await _cache.stats()
        if stats.get("total", 0) > 0:
            return
        try:
            result = await _sync_if_configured()
            logger.info("Cache warm-up: %s", result)
        except Exception:
            logger.exception("Cache warm-up sync failed")


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        config_manager = ConnectorConfig()
    connector_id = "pve2core"

    @app.on_event("startup")
    async def warm_cache_on_startup():
        """Populate the machine cache at boot so dependent plugins work
        immediately after a restart (the cache is in-memory only)."""
        async def _warm():
            # Jitter spreads the Proxmox load when several replicas boot together
            await asyncio.sleep(1 + random.random() * 4)
            try:
                result = await _sync_if_configured()
                logger.info("Startup cache warm-up: %s", result)
            except Exception:
                logger.exception("Startup cache warm-up failed")
        asyncio.create_task(_warm())

    @app.get("/api/plugins/pve2core/info")
    async def plugin_info():
        return {
            "plugin": "pve2core",
            "name": "PVE2 Core",
            "version": "0.1.0",
            "description": "Central connector for Proxmox data — other plugins depend on this",
            "status": "active",
        }

    @app.get("/api/plugins/pve2core/config")
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

    @app.post("/api/plugins/pve2core/config")
    async def save_config(body: CoreConfig):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        if audit:
            try:
                audit.log(connector_id, "INFO", "Config saved",
                          detail=f"Keys: proxmox_url, proxmox_token, proxmox_secret, enabled={body.enabled}")
            except Exception:
                pass
        success = config_manager.save_config(connector_id, body.model_dump(), body.enabled)
        # Mirror into the global settings table so /nodes, /vms, /storage,
        # /cluster/status and the sync engine see the same credentials.
        try:
            ConfigAdapter().save_settings(
                body.proxmox_url, body.proxmox_token, body.proxmox_secret, body.proxmox_insecure
            )
        except Exception as e:
            logger.exception("Failed to mirror pve2core config to global settings: %s", e)
        return {"saved": success, "connector": connector_id}

    @app.post("/api/plugins/pve2core/setup")
    async def setup_connection(body: CoreSetup):
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        try:
            client = await create_client_if_possible(
                body.proxmox_url, body.proxmox_token, body.proxmox_secret, insecure=body.proxmox_insecure
            )
            if not client:
                if audit:
                    try:
                        audit.log(connector_id, "ERROR", "Setup failed",
                                  detail="Could not create Proxmox client")
                    except Exception:
                        pass
                return {"connected": False, "error": "Could not create Proxmox client"}
            nodes = await client.get_nodes()
            await client.close()

            cfg = CoreConfig(
                enabled=True,
                proxmox_url=body.proxmox_url,
                proxmox_token=body.proxmox_token,
                proxmox_secret=body.proxmox_secret,
            )
            config_manager.save_config(connector_id, cfg.model_dump(), enabled=True)
            try:
                ConfigAdapter().save_settings(
                    body.proxmox_url, body.proxmox_token, body.proxmox_secret, body.proxmox_insecure
                )
            except Exception as e:
                logger.exception("Failed to mirror pve2core config to global settings: %s", e)
            config_manager.update_sync_state(connector_id, "success", items_synced=len(nodes))
            if audit:
                try:
                    audit.log(connector_id, "OK", "Setup complete",
                              detail=f"nodes_found: {len(nodes)}")
                except Exception:
                    pass
            logger.info("PVE2Core setup complete — %d nodes found", len(nodes))
            return {"connected": True, "nodes": len(nodes)}
        except Exception as e:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Setup failed",
                              detail=f"error: {e}")
                except Exception:
                    pass
            logger.exception("Setup failed: %s", e)
            return {"connected": False, "error": str(e)}

    async def _get_client() -> ProxmoxClient:
        if not config_manager:
            raise HTTPException(status_code=503, detail="Config manager unavailable")
        config = config_manager.get_config(connector_id)
        base = config.get("proxmox_url")
        insecure = config.get("proxmox_insecure", True)
        client = await create_client_if_possible(
            base, config.get("proxmox_token"), config.get("proxmox_secret"), insecure=insecure
        )
        if not client:
            raise HTTPException(status_code=503, detail="Could not create Proxmox client")
        return client

    @app.post("/api/plugins/pve2core/test")
    async def test_connection():
        if audit:
            try:
                audit.log(connector_id, "INFO", "Connection test started")
            except Exception:
                pass
        try:
            client = await _get_client()
            nodes = await client.get_nodes()
            await client.close()
            if audit:
                try:
                    audit.log(connector_id, "OK", "Connection test successful",
                              detail=f"nodes: {len(nodes)}")
                except Exception:
                    pass
            return {"connected": True, "nodes": len(nodes)}
        except HTTPException:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Connection test failed",
                              detail="Not configured")
                except Exception:
                    pass
            return {"connected": False, "error": "Not configured"}
        except Exception as e:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Connection test failed",
                              detail=f"error: {e}")
                except Exception:
                    pass
            return {"connected": False, "error": str(e)}

    @app.post("/api/plugins/pve2core/sync")
    async def trigger_sync():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        if not config.get("enabled"):
            if audit:
                try:
                    audit.log(connector_id, "WARNING", "Sync skipped",
                              detail="Connector not enabled")
                except Exception:
                    pass
            return {"error": "Connector not enabled"}
        try:
            client = await _get_client()
            collector = Collector(_cache, pve=client)
            stats = await collector.run()
            await client.close()
            config_manager.update_sync_state(
                connector_id, "success", items_synced=stats.get("total", 0)
            )
            if audit:
                try:
                    audit.log(connector_id, "OK", "Sync completed",
                              detail=f"nodes_ok: {stats.get('nodes_ok', 0)}\n"
                                     f"vms: {stats.get('vms', 0)}\n"
                                     f"lxcs: {stats.get('lxcs', 0)}\n"
                                     f"ips_fetched: {stats.get('ips_fetched', 0)}\n"
                                     f"errors: {stats.get('errors', 0)}\n"
                                     f"cache_size: {stats.get('total', 0)}")
                except Exception:
                    pass
            return {"status": "success", **stats}
        except HTTPException:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Sync failed",
                              detail="Not configured")
                except Exception:
                    pass
            return {"error": "Not configured"}
        except Exception as e:
            if audit:
                try:
                    audit.log(connector_id, "ERROR", "Sync failed",
                              detail=f"error: {e}")
                except Exception:
                    pass
            logger.exception("Sync failed: %s", e)
            if config_manager:
                config_manager.update_sync_state(connector_id, "error", error=str(e))
            return {"status": "error", "error": str(e)}

    @app.get("/api/plugins/pve2core/health", response_model=HealthResponse)
    async def health():
        last_sync = await _cache.last_sync()
        proxmox_connected = False
        try:
            client = await _get_client()
            await client.get_nodes()
            await client.close()
            proxmox_connected = True
        except Exception:
            pass
        stats = await _cache.stats()
        return HealthResponse(
            status="ok",
            last_sync=last_sync,
            proxmox_connected=proxmox_connected,
            cache_size=stats.get("total", 0),
        )

    @app.get("/api/plugins/pve2core/cache/stats")
    async def cache_stats():
        return await _cache.stats()

    @app.get("/api/plugins/pve2core/cluster", response_model=ClusterResponse)
    async def cluster():
        try:
            client = await _get_client()
            status = await client.get_cluster_status()
            ceph = await client.get_ceph_health()
            await client.close()
            online = sum(1 for m in status if m.get("status") == "online")
            return ClusterResponse(
                cluster_name="proxmox",
                quorum_status=f"{online}/{len(status)}",
                ceph_health=ceph.get("status") if ceph else None,
            )
        except Exception as e:
            logger.exception("Cluster info error: %s", e)
            return ClusterResponse()

    @app.get("/api/plugins/pve2core/machines", response_model=list[GenericMachine])
    async def list_machines(
        status: str = Query(None),
        machine_type: str = Query(None, alias="type"),
        node: str = Query(None),
        tag: str = Query(None),
    ):
        await _ensure_cache_warmed()
        return await _cache.get_filtered(
            status=status, machine_type=machine_type, node=node, tag=tag
        )

    @app.get("/api/plugins/pve2core/machines/{machine_id}", response_model=GenericMachine)
    async def get_machine(machine_id: str = Path(..., pattern=r"^\d+$")):
        machine = await _cache.get_by_id(machine_id)
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found in cache")
        return machine

    @app.post(
        "/api/plugins/pve2core/machines/{machine_id}/action/{action}",
        response_model=ActionResponse,
    )
    async def machine_action(
        machine_id: str = Path(..., pattern=r"^\d+$"),
        action: str = Path(..., pattern=r"^(start|stop|reboot|shutdown|suspend|resume|clone)$"),
    ):
        machine = await _cache.get_by_id(machine_id)
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found in cache")
        if audit:
            try:
                audit.log(connector_id, "CRITICAL",
                          f"Machine action: {action}",
                          detail=f"machine_id: {machine_id}\n"
                                 f"machine_name: {machine.name}\n"
                                 f"node: {machine.node}")
            except Exception:
                pass
        try:
            client = await _get_client()
            body = None
            if action == "clone":
                try:
                    nodes_data = await client.get_nodes()
                    all_vmids = set()
                    for node in nodes_data:
                        node_name = node.get("node", "")
                        try:
                            vms = await client.get_vms(node_name)
                            for vm in vms:
                                all_vmids.add(int(vm.get("vmid", 0)))
                            lxcs = await client.get_lxcs(node_name)
                            for lxc in lxcs:
                                all_vmids.add(int(lxc.get("vmid", 0)))
                        except Exception:
                            pass
                    newid = max(all_vmids) + 1 if all_vmids else int(machine_id) + 1000
                except Exception:
                    newid = int(machine_id) + 1000
                body = {"newid": str(newid)}
            task_id = await client.action_vm(machine.node, machine_id, action, body=body)
            await client.close()
            if not task_id:
                raise HTTPException(status_code=502, detail="Proxmox returned empty task ID")
            if audit:
                try:
                    audit.log(connector_id, "CRITICAL",
                              f"Machine action executed: {action}",
                              detail=f"machine_id: {machine_id}\n"
                                     f"task_id: {task_id}\n"
                                     f"result: ok")
                except Exception:
                    pass
            return ActionResponse(
                task_id=task_id, action=action, machine_id=machine_id
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Action %s failed for %s: %s", action, machine_id, e)
            raise HTTPException(status_code=502, detail=str(e)) from e

    @app.get("/api/plugins/pve2core/storage", response_model=list[StorageInfo])
    async def list_storage():
        try:
            client = await _get_client()
            data = await client.get_storage()
            disks = await client.get_disks()
            await client.close()
            result = []
            for s in data:
                total = s.get("total_disk") or 0
                used = s.get("used_disk") or 0
                result.append(StorageInfo(
                    id=s.get("id", ""),
                    name=s.get("name", ""),
                    node=s.get("node", ""),
                    type=s.get("type", "storage"),
                    total_gb=total // 1073741824 if total else 0,
                    used_gb=used // 1073741824 if used else 0,
                    content=", ".join(s.get("content", [])) if isinstance(s.get("content"), list) else str(s.get("content", "")),
                ))
            for d in disks:
                total = d.get("total_disk") or 0
                used = d.get("used_disk") or 0
                result.append(StorageInfo(
                    id=d.get("id", ""),
                    name=d.get("name", ""),
                    node=d.get("node", ""),
                    type="disk",
                    total_gb=total // 1073741824 if total else 0,
                    used_gb=used // 1073741824 if used else 0,
                    content="",
                ))
            return result
        except Exception as e:
            logger.exception("Storage list error: %s", e)
            return []

    @app.get("/api/plugins/pve2core/nodes", response_model=list[NodeInfo])
    async def list_nodes():
        try:
            client = await _get_client()
            data = await client._request("GET", "/nodes")
            await client.close()
            result = []
            for n in (data or []):
                uptime_val = n.get("uptime") or n.get("Uptime") or 0
                result.append(NodeInfo(
                    id=n.get("node", ""),
                    name=n.get("node", ""),
                    status=n.get("status", ""),
                    memory_mb=int(n.get("maxmem", 0) / 1024 / 1024) if n.get("maxmem") else 0,
                    uptime_sec=int(uptime_val),
                    maxcpu=n.get("maxcpu") or 0,
                    cpu_load=n.get("cpu") or n.get("cpu_load") or 0.0,
                ))
            return result
        except Exception as e:
            logger.exception("Nodes list error: %s", e)
            return []

    @app.get("/admin/pve2core", response_class=HTMLResponse)
    async def admin_page():
        configured = False
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            configured = bool(cfg.get("proxmox_url"))
        return HTMLResponse(content=build_page(configured=configured))
