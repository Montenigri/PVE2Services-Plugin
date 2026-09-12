"""OpenTofu state parser — converts `tofu show -json` output into canonical resources.

Push model: the CI pipeline posts the JSON output of `tofu show -json` (values
already resolved, no raw state, no backend credentials needed). One parser per
provider, all converging on the same canonical model (see schemas.CanonicalResource).
Day-0: bpg/proxmox. Telmate/proxmox is a later addition.
"""

import logging
from typing import Any, Dict, List, Tuple

from .schemas import CanonicalResource

logger = logging.getLogger("pve2drift.parser")

# Resource types of interest, mapped to the provider that owns them.
SUPPORTED_TYPES: Dict[str, str] = {
    "proxmox_virtual_environment_vm": "bpg",
    "proxmox_virtual_environment_container": "bpg",
    # Telmate legacy (day-2):
    # "proxmox_vm_qemu": "telmate",
    # "proxmox_lxc": "telmate",
}


class StateParseError(ValueError):
    """Raised when the payload is not a valid `tofu show -json` document."""


def parse_tofu_state(payload: Dict[str, Any]) -> Tuple[List[CanonicalResource], int]:
    """Extract VM/CT resources from a `tofu show -json` document.

    Returns (canonical_resources, skipped_types) where skipped_types counts
    managed resources whose type is not supported by any parser yet.
    Raises StateParseError when the document structure is not recognizable.
    """
    if not isinstance(payload, dict):
        raise StateParseError("payload must be a JSON object (output of `tofu show -json`)")
    values = payload.get("values")
    if not isinstance(values, dict):
        raise StateParseError(
            "missing 'values' section — is this the output of `tofu show -json`?"
        )
    root_module = values.get("root_module")
    if not isinstance(root_module, dict):
        raise StateParseError("missing 'values.root_module' section")

    resources: List[CanonicalResource] = []
    skipped = 0
    stack = [root_module]
    while stack:
        module = stack.pop()
        for res in module.get("resources", []) or []:
            if not isinstance(res, dict):
                continue
            if res.get("mode", "managed") != "managed":
                continue  # data sources carry no declarative state to compare
            rtype = res.get("type", "")
            if rtype not in SUPPORTED_TYPES:
                skipped += 1
                continue
            parsed = _parse_resource(res, SUPPORTED_TYPES[rtype])
            if parsed is not None:
                resources.append(parsed)
        for child in module.get("child_modules", []) or []:
            if isinstance(child, dict):
                stack.append(child)
    return resources, skipped


def _parse_resource(res: Dict[str, Any], provider: str) -> CanonicalResource:
    address = res.get("address", "")
    values = res.get("values", {}) or {}
    # The address already includes the module path and instance key
    # (e.g. module.foo.proxmox_virtual_environment_vm.bar["baz"]).
    if provider == "bpg":
        return _parse_bpg(address, res.get("type", ""), values)
    return CanonicalResource(
        resource_address=address, resource_type=res.get("type", ""), provider=provider
    )


def _parse_bpg(address: str, rtype: str, v: Dict[str, Any]) -> CanonicalResource:
    cpu = v.get("cpu") or {}
    memory = v.get("memory") or {}
    disks = v.get("disk") or []
    disk_sizes = [
        d.get("size") for d in disks if isinstance(d, dict) and d.get("size") is not None
    ]
    # Truncate like the live normalizer does (floor division on bytes), so the
    # two sides of the comparison use the same rounding.
    disk_gb = int(float(max(disk_sizes))) if disk_sizes else None
    tags = v.get("tags") or []
    tags = [str(t).strip() for t in tags if str(t).strip()]
    vmid = v.get("vm_id")
    return CanonicalResource(
        resource_address=address,
        resource_type=rtype,
        provider="bpg",
        node=v.get("node_name") or None,
        vmid=int(vmid) if vmid is not None else None,
        cores=int(cpu.get("cores")) if cpu.get("cores") is not None else None,
        memory_mb=int(memory.get("dedicated")) if memory.get("dedicated") is not None else None,
        disk_gb=disk_gb,
        tags=tags,
    )
