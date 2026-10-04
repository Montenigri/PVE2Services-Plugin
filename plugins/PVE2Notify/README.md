# PVE2 Notify

Monitors Proxmox state changes and dispatches notifications to **Discord**,
**Slack**, **Mattermost** and **Telegram**.

## Capabilities

- reads: `cluster_state`, `machine_cache`, `connector_config`
- writes: `notifications`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2notify/info` | GET | Plugin metadata |
| `/api/plugins/pve2notify/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2notify/test` | POST | Send a test notification |
| `/api/plugins/pve2notify/events` | GET | Recent/last detected events |
| `/api/plugins/pve2notify/sync` | POST | Detect changes and notify |
| `/api/plugins/pve2notify/scheduler/status` | GET | Background job status |
| `/api/plugins/pve2notify/scheduler/start` | POST | Start periodic checks |
| `/api/plugins/pve2notify/scheduler/stop` | POST | Stop periodic checks |
| `/admin/pve2notify` | GET | Admin UI |

## Assistant tools

None. Notification providers and event snapshots are runtime state (not a
persisted read-only data surface), so PVE2 Notify exposes no MCP tools.
