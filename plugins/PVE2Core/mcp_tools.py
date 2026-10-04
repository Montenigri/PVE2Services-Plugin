"""Read-only MCP tools exposed by PVE2 Core to the Winky assistant.

Handlers are resolved from ``plugin.yaml`` via ``mcp_tools:<name>`` and
registered by the core plugin loader. Every handler takes the argument object
the LLM produced and returns a JSON-serializable dict. Read-only by contract.
"""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.plugin_base import (
    get_core_health,
    get_core_machine,
    get_core_machines,
)


async def list_machines(params: dict[str, Any]) -> dict[str, Any]:
    """List every VM/LXC/node known to the machine cache."""
    machines = await get_core_machines()
    machine_type = params.get("type")
    node = params.get("node")
    if machine_type:
        machines = [m for m in machines if str(m.get("type")) == machine_type]
    if node:
        machines = [m for m in machines if str(m.get("node")) == node]
    return {"count": len(machines), "machines": machines}


async def get_machine(params: dict[str, Any]) -> dict[str, Any]:
    """Return a single machine by id from the machine cache."""
    machine = await get_core_machine(str(params.get("machine_id", "")))
    return {"found": machine is not None, "machine": machine}


async def cluster_health(params: dict[str, Any]) -> dict[str, Any]:
    """Return cache/proxmox connection health and last sync time."""
    return await get_core_health()
