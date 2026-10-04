# PVE2 Power

Schedules automatic **startup and shutdown** of VMs and LXC containers, with
separate weekday/weekend windows and per-day toggles.

## Capabilities

- reads: `machine_cache`, `node_state`, `connector_config`
- writes: `power_schedules`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2power/info` | GET | Plugin metadata |
| `/api/plugins/pve2power/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2power/test` | POST | Test the Proxmox connection |
| `/api/plugins/pve2power/machines` | GET | Machines available to schedule |
| `/api/plugins/pve2power/status` | GET | Scheduler status |
| `/api/plugins/pve2power/schedules/{machine_id}` | PUT/DELETE | One schedule |
| `/api/plugins/pve2power/sync` | POST | Evaluate schedules now |
| `/api/plugins/pve2power/scheduler/status` | GET | Background job status |
| `/api/plugins/pve2power/scheduler/start` | POST | Start the scheduler |
| `/api/plugins/pve2power/scheduler/stop` | POST | Stop the scheduler |
| `/admin/pve2power` | GET | Admin UI |

## Assistant tools (read-only)

`list_schedules`, `get_schedule`.
