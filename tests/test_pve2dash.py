"""Tests for PVE2Dash read-only MCP tools (no live Proxmox connection)."""

import asyncio

from PVE2Services.plugins.PVE2Dash import mcp_tools


def test_dashboard_summary_shape():
    out = asyncio.run(mcp_tools.dashboard_summary({}))
    assert set(out.keys()) == {"total", "by_type", "by_status", "health"}
    assert isinstance(out["total"], int)
    assert isinstance(out["by_type"], dict)
    assert isinstance(out["by_status"], dict)
