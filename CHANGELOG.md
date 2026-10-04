# Changelog

All notable changes to the PVE2Services plugin collection are documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-04

### Added

- Initial first-party plugin set: PVE2Core, PVE2Dash, PVE2Audit, PVE2DNS, PVE2LLM,
  PVE2Notify, PVE2NUT, PVE2Proxy, PVE2Power, PVE2Drift, PVE2 Wiki and the
  `example_plugin` template.
- Plugin manifest contract, shared-library usage and audit-logging guidelines
  (`PLUGIN_DEVELOPMENT.md`).
- Store build/sign/publish tooling wrappers (`tools/`).

### Changed

- **PVE2LLM — admin UI**: the system prompt default is now visible (textarea
  placeholder) with "Ripristina default" / "Svuota (usa default)" buttons, and
  the previously missing `max_tokens` and `temperature` fields are exposed. The
  Base URL placeholder/hint adapts to the selected provider.
- **PVE2LLM — admin UI restyled** to match the rest of the project (light
  theme, white cards, accent buttons, header with hub link, toast feedback).
  The page now lives in `templates/pve2llm_admin.html` like the other plugins,
  instead of a dark inline page.

### Fixed

- **PVE2Core — tags parsing**: the machine normalizer split the Proxmox `tags`
  property on commas, but Proxmox returns it **semicolon-separated** (`a;b`),
  so a VM/CT with more than one tag was exposed as a single tag — breaking
  tag-based consumers such as PVE2Drift matching. Both `;` and `,` are now
  accepted.
- **PVE2LLM — local OpenAI-compatible servers (vLLM/llama.cpp/Unsloth)** no
  longer require an API key: a custom `base_url` is treated as self-hosted, so
  `/test` and `/chat` work without one (previously `/test` failed with
  "openai requires an API key" before calling the server). When `base_url` has
  no path, `/v1` is appended automatically, and `/test` errors now include the
  attempted URL and the server response.
- **PVE2Proxy — input normalisation**: `base_domain`, `ssh_host`,
  `nginx_output_path` and `traefik_output_dir` now have a leading URL scheme
  (`http://`, `https://`, `ssh://`, …) and trailing slashes stripped on save,
  so pasted values like `http://192.168.1.5/` no longer leak into the stored
  config or the generated proxy config.
- **PVE2Proxy — Traefik**: the generated YAML is now correctly nested under
  `http:` (routers/services were emitted as siblings of `routers:`, so Traefik
  rejected the file with "field not found"), and it is written to a named
  `pve2proxy.yml` file inside `traefik_output_dir` instead of onto the
  directory itself (which produced an extension-less file the file provider
  ignored). The unsupported `cache` middleware is no longer emitted for
  Traefik (`rate_limit` maps to `RateLimit`).
- **PVE2Proxy — nginx zones**: the generated config now defines the
  `proxy_cache_path` / `limit_req_zone` directives when any mapping uses
  `cache` or `rate_limit`; previously it referenced zones that were never
  declared, so `nginx -t` and the reload failed (the deployer reported a
  warning, leaving the old config active).
- **PVE2DNS — AdGuard Home**: the provider now authenticates with HTTP Basic
  auth (it previously looked for a `session` cookie/JSON token that AdGuard
  never sends) and makes creates idempotent by listing rewrites first — AdGuard
  stores duplicate entries, so repeated syncs used to pile them up.
- **PVE2DNS — Pi-hole v6 support**: the provider now speaks the v6 REST API
  (`POST /api/auth` → `X-FTL-SID`, local DNS via `/api/config/dns/hosts`),
  selected by `pihole_api_version` (default `v6`). Legacy v5 stays supported and
  its connection test was fixed (it probed the bare endpoint and always failed).
  The admin UI now exposes the API-version selector.

[Unreleased]: https://github.com/Montenigri/PVE2Services-Plugin/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Montenigri/PVE2Services-Plugin/releases/tag/v0.1.0
