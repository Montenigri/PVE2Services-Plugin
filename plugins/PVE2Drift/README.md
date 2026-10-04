# PVE2 Drift

Detects **drift** between OpenTofu/Terraform declared state and the live
Proxmox cluster, using tag-based matching and **push ingestion from CI**
(authenticated by per-environment API keys).

## Capabilities

- reads: `cluster_state`, `machine_cache`, `connector_config`
- writes: `drift_state`, `audit_findings`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2drift/info` | GET | Plugin metadata |
| `/api/plugins/pve2drift/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2drift/test` | POST | Test configuration |
| `/api/plugins/pve2drift/sync` | POST | Compare declared vs live state |
| `/api/plugins/pve2drift/resources` | GET | Managed (declared) resources |
| `/api/plugins/pve2drift/drifts` | GET | Drift events |
| `/api/plugins/pve2drift/tf-snippet` | GET | Generated Terraform snippet |
| `/api/plugins/pve2drift/apikeys` | GET/POST | List/create ingestion API keys |
| `/api/plugins/pve2drift/apikeys/{key_id}` | DELETE | Revoke an API key |
| `/api/plugins/pve2drift/scheduler/status` | GET | Background job status |
| `/api/plugins/pve2drift/scheduler/start` | POST | Start periodic checks |
| `/api/plugins/pve2drift/scheduler/stop` | POST | Stop periodic checks |
| `/api/v1/state/ingest` | POST | CI push ingestion endpoint |
| `/admin/pve2drift` | GET | Admin UI |

## Assistant tools (read-only)

`list_managed_resources`, `list_open_drifts`, `list_drift_events`.
