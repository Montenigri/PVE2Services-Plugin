"""Diff engine: poll PVE2Core → compare snapshot → fire events."""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger("pve2notify.watcher")


def _machines_to_snapshot(machines: List[dict]) -> Dict[str, str]:
    return {m.get("id", str(m.get("machine_id", ""))): m.get("status", "unknown") for m in machines}


def _machines_by_id(machines: List[dict]) -> Dict[str, dict]:
    return {m.get("id", str(m.get("machine_id", ""))): m for m in machines}


async def fetch_machines_from_core(base_url: str = "") -> List[dict]:
    from PVE2Services.libs.plugin_base import get_core_machines

    machines = await get_core_machines()
    if not machines:
        logger.warning("PVE2Core cache empty — run PVE2Core sync first")
    return machines


def diff_snapshots(
    previous: Dict[str, str],
    current: Dict[str, str],
    current_machines: Dict[str, dict],
) -> List[dict]:
    events: List[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    # detect removed
    for mid, prev_status in previous.items():
        if mid not in current:
            events.append({
                "event_type": "removed",
                "machine_id": mid,
                "machine_name": "",
                "machine_type": "",
                "node": "",
                "status": prev_status,
                "previous_status": prev_status,
                "timestamp": now,
            })

    for mid, cur_status in current.items():
        machine = current_machines.get(mid, {})
        base = {
            "machine_id": mid,
            "machine_name": machine.get("name", ""),
            "machine_type": machine.get("type", "vm"),
            "node": machine.get("node", ""),
            "status": cur_status,
            "timestamp": now,
        }

        if mid not in previous:
            events.append({**base, "event_type": "added", "previous_status": ""})
        else:
            prev_status = previous[mid]
            if prev_status == "running" and cur_status != "running":
                events.append({**base, "event_type": "stopped", "previous_status": prev_status})
            elif prev_status != "running" and cur_status == "running":
                events.append({**base, "event_type": "started", "previous_status": prev_status})

    return events


def load_snapshot(config: dict) -> Dict[str, str]:
    raw = config.get("_snapshot", "{}")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def save_snapshot(config: dict, machines: List[dict]) -> dict:
    config["_snapshot"] = json.dumps(_machines_to_snapshot(machines))
    return config
