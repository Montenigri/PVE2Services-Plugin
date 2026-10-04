# PVE2 Dash

Lightweight **read-only** dashboard for Proxmox cluster health. It reads the
machine cache and can fetch per-entity RRD history directly from Proxmox.

## Capabilities

- reads: `cluster_state`, `machine_cache`
- writes: *(none)*

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2dash/info` | GET | Plugin metadata |
| `/api/plugins/pve2dash/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2dash/test` | POST | Test the Proxmox connection |
| `/api/plugins/pve2dash/sync` | POST | No-op (read-only) |
| `/api/plugins/pve2dash/history/{entity_id}` | GET | RRD history for an entity |
| `/admin/pve2dash` | GET | Admin UI |

## Assistant tools (read-only)

`dashboard_summary` — machine counts by type and status plus cache health.
