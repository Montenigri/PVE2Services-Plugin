# PVE2 Wiki

Syncs Proxmox infrastructure to **Wiki.js** via GraphQL, creating and updating
one wiki page per tracked entity (nodes, VMs, LXC, storage).

## Capabilities

- reads: `machine_cache`, `cluster_state`, `connector_config`
- writes: `wiki_pages`, `sync_state`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2wiki/info` | GET | Plugin metadata |
| `/api/plugins/pve2wiki/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2wiki/test` | POST | Test the Wiki.js connection |
| `/api/plugins/pve2wiki/status` | GET | Sync status |
| `/api/plugins/pve2wiki/entities` | GET | Tracked entities |
| `/api/plugins/pve2wiki/pages` | GET | Synced wiki pages |
| `/api/plugins/pve2wiki/templates` | GET | Page templates |
| `/api/plugins/pve2wiki/templates/{type_key}` | PUT | Save a template |
| `/api/plugins/pve2wiki/templates/reset` | POST | Reset templates to defaults |
| `/api/plugins/pve2wiki/sync` | POST | Sync pages to Wiki.js |
| `/admin/pve2wiki` | GET | Admin UI |

## Assistant tools (read-only)

`list_pages`, `get_page`, `list_sync_state`.
