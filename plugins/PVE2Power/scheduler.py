"""Schedule checker: compare current time against schedules and take action."""

import logging
from datetime import datetime, timezone
from typing import Optional

from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.libs.plugin_base import get_core_machine, update_core_machine_status

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

logger = logging.getLogger("pve2power.scheduler")

WEEKDAY_MAP = {
    0: "monday", 1: "tuesday", 2: "wednesday",
    3: "thursday", 4: "friday", 5: "saturday", 6: "sunday",
}


def _parse_hhmm(t: str) -> tuple[int, int]:
    parts = t.strip().split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def _to_minutes(h: int, m: int) -> int:
    return h * 60 + m


def should_be_on(schedule: dict, now: datetime, timezone_offset: int = 0) -> bool:
    """Check if a machine should be ON according to its schedule.

    timezone_offset: minutes from UTC (e.g., UTC+1 = 60, UTC+5:30 = 330).
    """
    total_minutes = (now.hour * 60 + now.minute + timezone_offset) % (24 * 60)
    local_h = total_minutes // 60
    local_m = total_minutes % 60
    now_min = _to_minutes(local_h, local_m)

    # Determine which day it is, and which schedule to use
    day_name = WEEKDAY_MAP.get(now.weekday(), "monday")

    if not schedule.get(day_name, True):
        return False  # Today is not an active day

    is_weekend = now.weekday() >= 5
    start_str = schedule["weekend_start_time"] if is_weekend else schedule["weekday_start_time"]
    stop_str = schedule["weekend_stop_time"] if is_weekend else schedule["weekday_stop_time"]

    start_h, start_m = _parse_hhmm(start_str)
    stop_h, stop_m = _parse_hhmm(stop_str)
    start_min = _to_minutes(start_h, start_m)
    stop_min = _to_minutes(stop_h, stop_m)

    if start_min <= stop_min:
        return start_min <= now_min < stop_min
    else:
        return now_min >= start_min or now_min < stop_min


def _current_time_key(now: datetime, tz_offset: int) -> str:
    h = (now.hour + tz_offset // 60) % 24
    return f"{h:02d}:{now.minute:02d}"


async def check_and_act(
    tz_offset: int = 0,
    dry_run: bool = False,
) -> dict:
    """Check all enabled schedules and take action if needed.

    Returns summary of actions taken.
    """
    db = DBAdapter()
    schedules = db.get_power_schedules()
    enabled = [s for s in schedules if s.get("enabled")]

    if not enabled:
        return {"checked": 0, "actions": [], "errors": []}

    now = datetime.now(timezone.utc)
    actions = []
    errors = []

    for s in enabled:
        mid = s["machine_id"]
        try:
            expected = should_be_on(s, now, tz_offset)

            actual_status = await _fetch_machine_status(mid)
            if actual_status is None:
                continue

            if expected and actual_status != "running":
                action = "start"
            elif not expected and actual_status == "running":
                action = "stop"
            else:
                continue

            actions.append({"machine_id": mid, "action": action, "status": actual_status})

            if not dry_run:
                ok = await _execute_action(mid, action)
                if ok:
                    db.update_power_schedule_action(mid, action)
                    # Keep the cache consistent with reality so subsequent
                    # checks (and the UI) don't act on a stale status.
                    await update_core_machine_status(
                        mid, "stopped" if action == "stop" else "running"
                    )
                else:
                    errors.append(f"{mid}: {action} failed")

        except Exception as e:
            errors.append(f"{mid}: {e}")
            logger.exception("Schedule check failed for %s", mid)

    if audit:
        try:
            audit.log("pve2power", "INFO", "Power check completed",
                      detail=f"schedules_checked: {len(enabled)}\n"
                             f"actions_taken: {len(actions)}\n"
                             f"errors: {len(errors)}")
        except Exception:
            pass
    return {"checked": len(enabled), "actions": actions, "errors": errors}


async def _fetch_machine_status(machine_id: str, core_base_url: str = "") -> Optional[str]:
    """Fresh status straight from Proxmox.

    The core cache is a snapshot and can be stale — e.g. the scheduler itself
    just stopped/started this machine, or someone toggled it in the Proxmox UI
    since the last sync. Acting on stale status would skip needed actions or
    double-fire them. Identity (node/type) comes from the cache; falls back to
    the cached status only if Proxmox is unreachable.
    """
    machine = await get_core_machine(machine_id)
    if machine is None:
        logger.warning("Machine %s not found in PVE2Core cache", machine_id)
        return None

    from PVE2Services.core.wiki_service.app.proxmox_adapter import create_client_if_possible

    client = await create_client_if_possible(None, None, None)
    if client:
        try:
            status = await client.get_machine_status(
                machine.get("node"), str(machine_id), machine.get("type")
            )
            if status:
                return status
        except Exception as e:
            logger.warning("Fresh status fetch failed for %s, using cache: %s", machine_id, e)
        finally:
            await client.close()

    return machine.get("status")


async def _execute_action(machine_id: str, action: str, core_base_url: str = "") -> bool:
    """Execute start/stop directly against Proxmox using the global settings."""
    from PVE2Services.core.wiki_service.app.proxmox_adapter import create_client_if_possible

    client = await create_client_if_possible(None, None, None)
    if not client:
        logger.error("Action %s on %s failed: no Proxmox client (check global settings)", action, machine_id)
        return False
    try:
        machine = await get_core_machine(machine_id)
        if not machine:
            logger.error("Action %s on %s failed: machine not in cache", action, machine_id)
            return False
        node = machine.get("node")
        pve_type = machine.get("type")
        if not node or pve_type not in ("vm", "lxc"):
            logger.error("Action %s on %s failed: invalid machine data", action, machine_id)
            return False
        await client.action_machine(node, machine_id, pve_type, action)
        if audit:
            try:
                audit.log("pve2power", "OK", f"Action executed: {action}",
                          detail=f"machine_id: {machine_id}\n"
                                 f"node: {node}\n"
                                 f"type: {pve_type}\n"
                                 f"result: ok")
            except Exception:
                pass
        logger.info("Action %s on %s OK", action, machine_id)
        return True
    except Exception as e:
        if audit:
            try:
                audit.log("pve2power", "ERROR", f"Action failed: {action}",
                          detail=f"machine_id: {machine_id}\n"
                                 f"error: {e}")
            except Exception:
                pass
        logger.error("Action %s on %s failed: %s", action, machine_id, e)
        return False
    finally:
        await client.close()
