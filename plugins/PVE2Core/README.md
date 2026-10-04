# PVE2 Core

Central connector for Proxmox data. PVE2Core authenticates to the Proxmox API
and populates the shared in-memory **machine cache** (nodes, VMs, LXC, storage)
that the other plugins read.

## Capabilities

- reads: `cluster_state`
- writes: `machine_cache`, `sync_state`

## Configuration

Proxmox endpoint and API token, stored via `ConnectorConfig` (`pve2core`). The
Proxmox secret is encrypted at rest. Use `/api/plugins/pve2core/setup` or the
admin page to configure.

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2core/info` | GET | Plugin metadata |
| `/api/plugins/pve2core/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2core/setup` | POST | Initial Proxmox setup |
| `/api/plugins/pve2core/test` | POST | Test the Proxmox connection |
| `/api/plugins/pve2core/sync` | POST | Refresh the machine cache |
| `/api/plugins/pve2core/machines` | GET | List cached machines |
| `/api/plugins/pve2core/machines/{machine_id}` | GET | One cached machine |
| `/api/plugins/pve2core/nodes` | GET | Cluster nodes |
| `/api/plugins/pve2core/storage` | GET | Storage |
| `/api/plugins/pve2core/cluster` | GET | Cluster status |
| `/api/plugins/pve2core/cache/stats` | GET | Cache statistics |
| `/api/plugins/pve2core/health` | GET | Connection/cache health |
| `/admin/pve2core` | GET | Admin UI |

## Assistant tools (read-only)

`list_machines`, `get_machine`, `cluster_health`.
