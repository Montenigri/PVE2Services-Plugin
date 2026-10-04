# PVE2 Proxy

Reverse proxy configuration generator with **SSH deploy**. It builds Nginx
server blocks from machine mappings and deploys them to the target host.

## Capabilities

- reads: `machine_cache`, `connector_config`
- writes: `proxy_configs`

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/pve2proxy/info` | GET | Plugin metadata |
| `/api/plugins/pve2proxy/config` | GET/POST | Read/save configuration |
| `/api/plugins/pve2proxy/test` | POST | Test SSH/connection |
| `/api/plugins/pve2proxy/machines` | GET | Machines available to map |
| `/api/plugins/pve2proxy/mappings` | GET | Proxy mappings |
| `/api/plugins/pve2proxy/mappings/{machine_id}` | PUT/DELETE | One mapping |
| `/api/plugins/pve2proxy/mappings/bulk` | POST | Bulk create/update |
| `/api/plugins/pve2proxy/generate` | POST | Generate config |
| `/api/plugins/pve2proxy/deploy` | POST | Deploy generated config |
| `/api/plugins/pve2proxy/sync` | GET | Sync status |
| `/admin/pve2proxy` | GET | Admin UI |

## Nginx output

The generated file contains one `server` block per enabled mapping and is
meant to live in `conf.d/` (included inside `http {}`). When any mapping uses
`cache` or `rate_limit`, the file also emits the required http-context zones
(`proxy_cache_path`, `limit_req_zone`) so the config is self-consistent and
`nginx -t` passes. `ssl_enabled` expects the certificates to already exist at
`/etc/letsencrypt/live/<domain>/`.

## Traefik output

Writes a single `pve2proxy.yml` into `traefik_output_dir` (the file provider
watches the directory and loads `*.yml`). `rate_limit` becomes a `RateLimit`
middleware; `cache` is a **no-op** here because Traefik has no built-in
response-cache middleware (it is an nginx-only feature). No reload command is
needed — Traefik's file provider watches the directory.

## Assistant tools (read-only)

`list_mappings`, `get_mapping`.
