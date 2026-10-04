# PVE2 NUT

NUT (Network UPS Tools) dashboard — multi-server **UPS monitoring** with
history charts, events and instant commands.

## Capabilities

- reads: `connector_config`
- writes: `sync_state`, `nut_history`, `nut_events`, `notifications`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2nut/info` | GET | Plugin metadata |
| `/api/plugins/pve2nut/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2nut/test` | POST | Test NUT server connectivity |
| `/api/plugins/pve2nut/devices` | GET | Monitored UPS devices |
| `/api/plugins/pve2nut/history/{ups_name}` | GET | UPS history |
| `/api/plugins/pve2nut/events` | GET | UPS events |
| `/api/plugins/pve2nut/clients/{ups_name}` | GET | Connected clients |
| `/api/plugins/pve2nut/commands/{ups_name}` | GET | Available instant commands |
| `/api/plugins/pve2nut/command/{ups_name}/{command}` | POST | Run an instant command |
| `/api/plugins/pve2nut/sync` | POST | Poll NUT servers |
| `/api/plugins/pve2nut/scheduler/status` | GET | Background job status |
| `/api/plugins/pve2nut/scheduler/start` | POST | Start polling |
| `/api/plugins/pve2nut/scheduler/stop` | POST | Stop polling |
| `/admin/pve2nut` | GET | Admin UI |

## Assistant tools (read-only)

`list_devices`, `last_reading`, `get_history`, `list_events`.
