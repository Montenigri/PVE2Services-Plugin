"""Tests for PVE2Core read-only MCP tools (no live Proxmox connection)."""

import asyncio

from PVE2Services.plugins.PVE2Core import mcp_tools


def test_list_machines_shape():
    out = asyncio.run(mcp_tools.list_machines({}))
    assert set(out.keys()) == {"count", "machines"}
    assert isinstance(out["machines"], list)


def test_list_machines_filters_accepted():
    out = asyncio.run(mcp_tools.list_machines({"type": "qemu", "node": "pve1"}))
    assert out["count"] == len(out["machines"])


def test_get_machine_missing_returns_found_false():
    out = asyncio.run(mcp_tools.get_machine({"machine_id": "vm/999999"}))
    assert out["found"] is False
    assert out["machine"] is None


def test_cluster_health_shape():
    out = asyncio.run(mcp_tools.cluster_health({}))
    for key in ("status", "proxmox_connected", "cache_size", "last_sync"):
        assert key in out


def test_normalize_machine_parses_semicolon_tags():
    """Proxmox returns the tags property semicolon-separated ('a;b')."""
    from PVE2Services.plugins.PVE2Core.normalizer import normalize_machine

    m = normalize_machine(
        {"vmid": 901, "tags": "pve2-managed-aaa;web;prod", "cpus": 2, "maxmem": 2097152},
        node="pve", machine_type="qemu", ips=[],
    )
    assert m.tags == ["pve2-managed-aaa", "web", "prod"]
    # comma form still supported; empty/absent -> []
    assert normalize_machine({"vmid": 1, "tags": "a,b"}, node="pve", machine_type="qemu", ips=[]).tags == ["a", "b"]
    assert normalize_machine({"vmid": 2}, node="pve", machine_type="qemu", ips=[]).tags == []
