import logging
from datetime import datetime, timezone

from PVE2Services.core.wiki_service.app.proxmox_adapter import ProxmoxClient

from .cache import MachineCache
from .normalizer import normalize_machine

logger = logging.getLogger("pve2core.collector")


class Collector:
    def __init__(self, cache: MachineCache, pve: ProxmoxClient):
        self.cache = cache
        self.pve = pve

    async def run(self) -> dict:
        temp: dict = {}
        stats = {"nodes_ok": 0, "nodes_skip": 0, "vms": 0, "lxcs": 0, "errors": 0, "ips_fetched": 0}

        nodes = await self.pve.get_nodes()
        for node_data in nodes:
            node = node_data.get("name")
            if node_data.get("status") != "online":
                stats["nodes_skip"] += 1
                continue
            stats["nodes_ok"] += 1

            try:
                vms = await self.pve._request("GET", f"/nodes/{node}/qemu")
            except Exception as e:
                logger.exception("Failed to fetch VMs for node %s: %s", node, e)
                vms = []

            for vm in (vms or []):
                vmid = str(vm.get("vmid", ""))
                # Cache stopped machines too — the power scheduler needs their
                # status to start them. IP discovery only works on running VMs.
                running = vm.get("status") == "running"
                ips: list = []
                if running:
                    try:
                        ips = await self.pve.agent_network_interfaces(node, vmid)
                        stats["ips_fetched"] += 1
                    except Exception:
                        pass
                try:
                    machine = normalize_machine(vm, node, "vm", ips)
                    temp[machine.id] = machine
                    stats["vms"] += 1
                except Exception as e:
                    logger.exception("Failed to normalize VM %s/%s: %s", node, vmid, e)
                    stats["errors"] += 1

            try:
                lxcs = await self.pve._request("GET", f"/nodes/{node}/lxc")
            except Exception as e:
                logger.exception("Failed to fetch LXCs for node %s: %s", node, e)
                lxcs = []

            for ct in (lxcs or []):
                ctid = str(ct.get("vmid", ""))
                try:
                    machine = normalize_machine(ct, node, "lxc", [])
                    temp[machine.id] = machine
                    stats["lxcs"] += 1
                except Exception as e:
                    logger.exception("Failed to normalize LXC %s/%s: %s", node, ctid, e)
                    stats["errors"] += 1

        await self.cache.swap(temp, datetime.now(timezone.utc))
        stats["total"] = len(temp)
        return stats
