# Example Plugin

A minimal, self-contained template that demonstrates the PVE2Services plugin
contract:

- a validated `plugin.yaml` manifest;
- `load_plugin(app)` registering the required endpoints
  (`/info`, `/config`, `/test`, `/sync`) plus an admin page;
- configuration via `ConnectorConfig`;
- audit-logging hooks (`libs.audit`);
- error handling via `libs.errors.PluginError`.

Use it as the starting point for a new plugin. It has no domain data and
therefore exposes no assistant (MCP) tools.

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/example_plugin/info` | GET | Plugin metadata |
| `/api/plugins/example_plugin/config` | GET/POST | Read/save configuration |
| `/api/plugins/example_plugin/test` | POST | Test connection |
| `/api/plugins/example_plugin/sync` | POST | Placeholder sync |
| `/admin/example_plugin` | GET | Admin UI |

See [`../../PLUGIN_DEVELOPMENT.md`](../../PLUGIN_DEVELOPMENT.md) for the full
contract.
