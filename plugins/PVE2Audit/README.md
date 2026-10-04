# PVE2 Audit

Resource analysis and **rightsizing recommendations** for the cluster. It
collects resource history and produces actionable recommendations (over/under
provisioning, idle machines, …).

## Capabilities

- reads: `cluster_state`, `machine_cache`, `audit_log`
- writes: `audit_findings`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2audit/info` | GET | Plugin metadata |
| `/api/plugins/pve2audit/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2audit/test` | POST | Test configuration |
| `/api/plugins/pve2audit/sync` | POST | Collect history + recompute findings |
| `/api/plugins/pve2audit/recommendations` | GET | Active recommendations |
| `/api/plugins/pve2audit/recommendations/{rec_id}` | GET | One recommendation |
| `/api/plugins/pve2audit/recommendations/{rec_id}/apply` | POST | Mark as applied |
| `/api/plugins/pve2audit/report/summary` | GET | Counts by severity/category |
| `/api/plugins/pve2audit/report/nodes` | GET | Per-node report |
| `/api/plugins/pve2audit/history/{entity_id}` | GET | Resource history |
| `/admin/pve2audit` | GET | Admin UI |

## Assistant tools (read-only)

`list_recommendations`, `summary`, `entity_history`, `resource_aggregate`.
