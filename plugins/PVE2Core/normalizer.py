from typing import Any, Dict, List

from .schemas import GenericMachine


def normalize_machine(raw: Dict[str, Any], node: str, machine_type: str, ips: List[str]) -> GenericMachine:
    id_str = str(raw.get("vmid", ""))
    tags_raw = raw.get("tags", "")
    if isinstance(tags_raw, str):
        # Proxmox returns the tags property as a single string separated by
        # semicolons (e.g. "a;b"); older/CLI paths may use commas. Split on both.
        tags = [t.strip() for t in tags_raw.replace(";", ",").split(",") if t.strip()] if tags_raw else []
    else:
        tags = list(tags_raw) if tags_raw else []

    maxmem = raw.get("maxmem", 0) or 0
    mem = raw.get("mem", 0) or 0
    maxdisk = raw.get("maxdisk", 0) or 0
    disk = raw.get("disk", 0) or 0

    return GenericMachine(
        id=id_str,
        name=raw.get("name", "") or "",
        type=machine_type,
        node=node,
        status=raw.get("status", "unknown") or "unknown",
        uptime_sec=raw.get("uptime", 0) or 0,
        cores=raw.get("cpus", 0) or 0,
        memory_mb=maxmem // 1048576,
        used_mem_mb=mem // 1048576,
        disk_gb=maxdisk // 1073741824,
        used_disk_gb=disk // 1073741824,
        ip_addresses=ips,
        tags=tags,
    )


def extract_ips(agent_data: List[Dict[str, Any]]) -> List[str]:
    valid: List[str] = []
    for iface in agent_data or []:
        if iface.get("name") == "lo":
            continue
        for ip_obj in iface.get("ip-addresses", []):
            if ip_obj.get("ip-address-type") == "ipv4" and ip_obj.get("ip-address") != "127.0.0.1":
                valid.append(ip_obj["ip-address"])
    return valid
