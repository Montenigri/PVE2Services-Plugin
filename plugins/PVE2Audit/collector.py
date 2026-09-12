import logging
from typing import Dict, Optional

from PVE2Services.core.wiki_service.app.proxmox_adapter import ProxmoxClient
from PVE2Services.libs.db_adapter import DBAdapter

logger = logging.getLogger("pve2audit.collector")


class Collector:
    """Poll Proxmox RRD data for all running VMs/LXCs and store in resource_history."""

    def __init__(self, db: DBAdapter, pve: Optional[ProxmoxClient] = None):
        self.db = db
        self.pve = pve

    async def run(self, timeframe: str = "hour") -> Dict[str, int]:
        if not self.pve:
            return {"error": "Proxmox client not available", "collected": 0}

        collected = 0
        skipped = 0
        errors = 0

        for entity_list, prefix, entity_type in [
            (await self.pve.get_vms(), "vm-", "vm"),
            (await self.pve.get_lxcs(), "lxc-", "lxc"),
        ]:
            for ent in entity_list:
                if ent.get("status") != "running":
                    skipped += 1
                    continue

                vmid = ent.get("id", "").replace(prefix, "")
                node_name = ent.get("node")
                if not vmid or not node_name:
                    skipped += 1
                    continue

                pve_type = "qemu" if entity_type == "vm" else "lxc"
                try:
                    rrd = await self.pve.get_rrd_data(node_name, vmid, pve_type, timeframe)
                except Exception as e:
                    logger.warning("RRD poll failed for %s/%s: %s", node_name, vmid, e)
                    errors += 1
                    continue

                if not rrd:
                    skipped += 1
                    continue

                # Mean CPU over the RRD window (not just the last point) so a
                # single quiet minute doesn't mask activity inside the window;
                # cpu_max keeps the burst ceiling.
                cpu_values = [s.get("cpu", 0) for s in rrd if s.get("cpu") is not None]
                cpu_mean = sum(cpu_values) / len(cpu_values) if cpu_values else 0.0
                last = rrd[-1]
                self.db.insert_resource_history(
                    entity_id=ent["id"],
                    node=node_name,
                    entity_type=entity_type,
                    cpu_avg=float(cpu_mean),
                    cpu_max=float(max(cpu_values)) if cpu_values else 0.0,
                    mem_used=int(last.get("mem", 0)),
                    mem_max=int(last.get("maxmem", 0)),
                    disk_used=int(last.get("disk", 0)) if last.get("disk") is not None else 0,
                    disk_max=int(last.get("maxdisk", 0)) if last.get("maxdisk") is not None else 0,
                    netin=int(last.get("netin", 0)),
                    netout=int(last.get("netout", 0)),
                )
                collected += 1

        logger.info("Collector: %d samples collected, %d skipped, %d errors", collected, skipped, errors)
        return {"collected": collected, "skipped": skipped, "errors": errors}
