"""Drift engine — compares declared state with live state and manages the
drift lifecycle (open on transition, resolve on realignment, no notification
spam: only state transitions produce findings)."""

import json
import logging
from typing import Any, Dict, List, Optional

from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.libs.plugin_base import get_core_health

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .matcher import build_live_index
from .schemas import DriftCheckResult

logger = logging.getLogger("pve2drift.engine")

PLUGIN_ID = "pve2drift"

# Canonical (declared) field -> GenericMachine (live) field.
LIVE_FIELD_MAP: Dict[str, str] = {
    "cores": "cores",
    "memory_mb": "memory_mb",
    "disk_gb": "disk_gb",
    "node": "node",
    "vmid": "id",
}

# bpg resource type -> generic machine type used by Audit.
TYPE_TO_MACHINE_TYPE = {
    "proxmox_virtual_environment_vm": "vm",
    "proxmox_virtual_environment_container": "lxc",
}

DEFAULT_TRACKED_FIELDS = ["cores", "memory_mb", "disk_gb", "node", "vmid"]


def _declared_json(resource: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data = json.loads(resource.get("declared_state") or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _eq(declared: Any, live: Any) -> bool:
    return str(declared) == str(live)


async def run_drift_check(
    tracked_fields: Optional[List[str]] = None,
    unmanaged_to_audit: bool = True,
) -> DriftCheckResult:
    """One drift cycle over every managed resource.

    The job never invokes OpenTofu: it compares the declared_state stored at
    the last ingestion with the live state the Core Agent already collects for
    the Dashboard.
    """
    db = DBAdapter()
    fields = [f for f in (tracked_fields or DEFAULT_TRACKED_FIELDS) if f in LIVE_FIELD_MAP]
    resources = db.get_managed_resources()
    by_tag, _untagged = await build_live_index()

    checked = opened = resolved = missing = unmanaged = 0
    errors: List[str] = []

    for res in resources:
        rid = res.get("id")
        address = res.get("resource_address", "")
        tag = res.get("matching_tag", "")
        try:
            checked += 1
            machine = by_tag.get(tag)
            if machine is None:
                if db.open_or_update_drift(
                    rid, "resource", declared_value=address, live_value="",
                    category="resource_missing",
                ):
                    opened += 1
                    _rec_drift(db, res, "resource", "", "critical")
                missing += 1
                db.touch_managed_resource_checked(rid)
                continue

            # Tag found again: a previous "resource deleted out-of-band" drift
            # is now resolved.
            if db.resolve_drift(rid, "resource"):
                resolved += 1
                _dismiss_rec(db, address, "resource")

            declared = _declared_json(res)
            for field in fields:
                if field not in declared or declared[field] is None:
                    continue  # field not covered by the provider: cannot compare
                live_value = machine.get(LIVE_FIELD_MAP[field])
                if _eq(declared[field], live_value):
                    if db.resolve_drift(rid, field):
                        resolved += 1
                        _dismiss_rec(db, address, field)
                else:
                    if db.open_or_update_drift(
                        rid, field, declared_value=str(declared[field]),
                        live_value=str(live_value) if live_value is not None else "",
                    ):
                        opened += 1
                        _rec_drift(db, res, field, str(live_value), "warning")
            db.touch_managed_resource_checked(rid)
        except Exception as e:  # one bad resource must not kill the cycle
            logger.exception("Drift check failed for %s", address)
            errors.append(f"{address}: {e}")

    # Machines carrying a managed tag but unknown to IaC go to the Audit, not
    # to the drift log (they are not drift).
    for tag, machine in by_tag.items():
        if db.get_managed_resource_by_tag(tag) is None:
            unmanaged += 1
            if unmanaged_to_audit:
                _rec_unmanaged(db, tag, machine)

    if audit:
        try:
            severity = "OK" if not (opened or missing or errors) else "WARNING"
            audit.log(PLUGIN_ID, severity, "Drift check completed",
                      detail=f"resources_checked: {checked}\n"
                             f"drift_opened: {opened}\n"
                             f"drift_resolved: {resolved}\n"
                             f"missing_resources: {missing}\n"
                             f"unmanaged: {unmanaged}\n"
                             f"errors: {len(errors)}")
        except Exception:
            pass

    return DriftCheckResult(
        checked=checked, opened=opened, resolved=resolved,
        missing=missing, unmanaged=unmanaged, errors=errors,
    )


def resolve_on_ingestion(db: DBAdapter, resource: Dict[str, Any],
                         declared: Dict[str, Any],
                         by_tag: Dict[str, Dict[str, Any]]) -> int:
    """Close open drifts for a resource whose fresh ingestion realigns it with
    the live state (the rule: a new ingestion mirroring live closes the drifts).

    The live half comes from the PVE2Core cache snapshot (`by_tag`, built by
    the async ingestion endpoint via matcher.build_live_index). Returns the
    number of drifts resolved.
    """
    machine = by_tag.get(resource.get("matching_tag", ""))
    if machine is None:
        return 0
    rid = resource.get("id")
    address = resource.get("resource_address", "")
    resolved = 0
    for field in LIVE_FIELD_MAP:
        if field not in declared or declared[field] is None:
            continue
        live_value = machine.get(LIVE_FIELD_MAP[field])
        if _eq(declared[field], live_value) and db.resolve_drift(rid, field):
            resolved += 1
            _dismiss_rec(db, address, field)
    # If the resource is live again, a pending "resource deleted out-of-band"
    # drift is settled too.
    if db.resolve_drift(rid, "resource"):
        _dismiss_rec(db, address, "resource")
        resolved += 1
    return resolved


def _rec_drift(db: DBAdapter, resource: Dict[str, Any], field: str,
               live_value: str, severity: str) -> None:
    try:
        db.save_recommendation(
            entity_id=f"drift:{resource.get('resource_address', '')}",
            entity_name=resource.get("resource_address", ""),
            entity_type=TYPE_TO_MACHINE_TYPE.get(resource.get("resource_type", ""), "vm"),
            node=resource.get("node") or "",
            category="drift",
            severity=severity,
            current_value=f"{field}: live={live_value}",
            suggested_value=f"{field}: declared={_declared_json(resource).get(field, '')}",
            rationale=(f"Drift detected between OpenTofu declared state and the live "
                       f"cluster (matching tag {resource.get('matching_tag', '')}). "
                       f"The system proposes: realign the module or accept the drift."),
        )
    except Exception:
        logger.exception("Failed to record audit recommendation for drift")


def _dismiss_rec(db: DBAdapter, address: str, field: str) -> None:
    try:
        for rec in db.get_recommendations(
                entity_id=f"drift:{address}", category="drift", active_only=True):
            if str(rec.get("current_value", "")).split(":", 1)[0].strip() == field:
                db.dismiss_recommendation(rec["id"])
    except Exception:
        logger.exception("Failed to dismiss audit recommendation after resolve")


def _rec_unmanaged(db: DBAdapter, tag: str, machine: Dict[str, Any]) -> None:
    entity_id = f"unmanaged:{machine.get('id', '')}"
    try:
        existing = db.get_recommendations(entity_id=entity_id, category="drift",
                                          active_only=True)
        for rec in existing:
            if rec.get("current_value") == tag:
                return  # already reported, no spam
        db.save_recommendation(
            entity_id=entity_id,
            entity_name=machine.get("name", ""),
            entity_type=machine.get("type", "vm"),
            node=machine.get("node", ""),
            category="drift",
            severity="warning",
            current_value=tag,
            suggested_value="",
            rationale=("Live machine carries a PVE2 managed tag but has no "
                       "matching OpenTofu resource: it is unmanaged by IaC. "
                       "The system proposes: import it or remove the tag."),
        )
    except Exception:
        logger.exception("Failed to record unmanaged-machine audit recommendation")


async def core_status() -> Dict[str, Any]:
    return await get_core_health()
