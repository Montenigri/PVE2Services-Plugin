# PVE2 DNS

DNS synchronization connector with **Pi-hole** and **AdGuard Home** support. It
maps cached Proxmox machines to DNS records and pushes them to the configured
resolver.

## Capabilities

- reads: `machine_cache`, `connector_config`
- writes: `dns_records`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2dns/info` | GET | Plugin metadata |
| `/api/plugins/pve2dns/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2dns/test` | POST | Test the resolver connection |
| `/api/plugins/pve2dns/machines` | GET | Machines available to map |
| `/api/plugins/pve2dns/records` | GET | Managed DNS records |
| `/api/plugins/pve2dns/records/{machine_id}` | GET/PUT/DELETE | One record |
| `/api/plugins/pve2dns/records/bulk` | POST | Bulk create/update |
| `/api/plugins/pve2dns/sync` | POST | Push records to the resolver |
| `/admin/pve2dns` | GET | Admin UI |

## Pi-hole

Select the API generation with `pihole_api_version` (default **v6**):

| Version | Auth | Local DNS records |
|---|---|---|
| `v6` (current) | `POST /api/auth` with the **web password** → session id (`X-FTL-SID`) | `GET/PUT/DELETE /api/config/dns/hosts` (`"<ip> <hostname>"`) |
| `v5` (legacy) | `/admin/api.php` with the **API token hash** (`auth=`) | not supported — Pi-hole v5 has no REST endpoint for `custom.list` |

For v6 the config field `pihole_token` is the Pi-hole web/API **password**.

## AdGuard Home

Authenticates with the admin **username/password** via HTTP Basic auth on every
`/control/*` call. Records are created as AdGuard **DNS rewrites**
(`/control/rewrite/add`). AdGuard stores duplicate rewrites, so sync lists
first and skips entries that already exist (idempotent); disabling a record
deletes the matching rewrite.

## Assistant tools (read-only)

`list_records`, `get_record`.
