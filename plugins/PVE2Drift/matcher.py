"""Tag-based matching between declared IaC resources and live machines.

The vmid is deliberately NOT the join key: with bpg `vm_id` is often computed
or optional and gets reassigned when a resource is recreated. Each managed
resource carries a unique tag injected by the Terraform/OpenTofu module; the
join becomes tag → declared resource. The vmid remains an attribute to compare.
"""

import hashlib

from PVE2Services.libs.plugin_base import get_core_machines

TAG_PREFIX = "pve2-managed-"


def matching_tag_for(resource_address: str) -> str:
    """Stable unique tag for a resource address, valid for the PVE tag charset
    (letters, digits, `_ - . / +` — no colons)."""
    digest = hashlib.sha256(resource_address.encode()).hexdigest()[:12]
    return f"{TAG_PREFIX}{digest}"


def is_matching_tag(tag: str) -> bool:
    return isinstance(tag, str) and tag.startswith(TAG_PREFIX) and len(tag) > len(TAG_PREFIX)


async def build_live_index() -> tuple[dict, list]:
    """Index live machines from the PVE2Core cache by their managed tags.

    Returns (by_tag, untagged_machines): by_tag maps a managed tag to the
    machine dict, untagged_machines lists machines carrying no managed tag.
    """
    machines = await get_core_machines()
    by_tag: dict = {}
    untagged: list = []
    for m in machines:
        tags = m.get("tags") or []
        mine = [t for t in tags if is_matching_tag(t)]
        if not mine:
            untagged.append(m)
            continue
        for t in mine:
            by_tag.setdefault(t, m)
    return by_tag, untagged
