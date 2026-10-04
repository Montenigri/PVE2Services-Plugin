# Plugin Development Guide

This guide explains how to develop custom plugins for PVE2Services.

## Plugin Structure

A plugin is a Python package under the `plugins/` directory with this structure:

```
plugins/
  my_plugin/
    __init__.py      # Required: exports load_plugin()
    plugin.yaml      # Required: plugin manifest (see below)
    frontend.py      # Optional: HTML page builder
    providers.py     # Optional: External API clients
    schemas.py       # Optional: Pydantic models
    watcher.py       # Optional: Background tasks
```

## Plugin Manifest (plugin.yaml)

Every plugin ships a manifest; the loader validates it **before importing**
your code — an incompatible manifest means the plugin is skipped with a
logged reason instead of possibly crashing the core at import time.

```yaml
id: my_plugin                  # lowercase identifier, = directory name
name: My Custom Plugin
version: 0.1.0                 # strict X.Y.Z semver
core_compat: ">=0.1.0,<2.0.0"  # core version range this plugin supports
entrypoint: "__init__:load_plugin"   # default; "pkg.mod:function" also works
description: What the plugin does
author: Your Name
icon: "🔌"
capabilities:
  reads: [vm_state, machine_cache]    # what data the plugin reads
  writes: [notifications]             # what state the plugin produces
trust_tier: trusted                   # display-only; effective tier is
                                      # derived from package provenance
license_required: false               # future: paid trusted plugins
license_server_url: null
```

Validation rules enforced by the schema (`libs/plugin_manifest.py`):

- `id` — lowercase slug `[a-z][a-z0-9_-]{1,63}`; installed (store) plugins
  must match the directory name and the requested id.
- `version` — strict 3-part semver `X.Y.Z` (optional `-pre-release`/`+build`).
- `core_compat` — PEP 440 specifier set checked against the running core.
- `entrypoint` — `"module:function"`; `__init__` maps to the package module.
- `checksum` — `sha256:<64 hex>` of the built `package.zip` (set by the CI).
- Unknown top-level fields are rejected (typos fail loud, not silent).
- `trust_tier` must be `trusted` or `third_party`, but is **display-only**:
  the loader derives the effective tier from the verified signature/origin
  (see [docs/PLUGIN_STORE.md](https://github.com/Montenigri/pve2service-core/blob/main/docs/PLUGIN_STORE.md)).

Capability vocabulary (add yours freely — unknown ones are logged, not
rejected): reads `cluster_state`, `node_state`, `vm_state`, `storage_state`,
`machine_cache`, `connector_config`, `audit_log`, `dns_records`,
`power_schedules`, `proxy_configs`, `audit_recommendations`, `drift_state`,
`nut_history`, `nut_events`, `wiki_pages`, `sync_state`, `changelog`; writes
`machine_cache`, `sync_state`, `audit_findings`, `notifications`, `dns_records`,
`power_schedules`, `proxy_configs`, `wiki_pages`, `db_settings`.

## MCP Tools (Winky assistant)

Plugins can expose read-only data to the **PVE2LLM** assistant (name: *Winky*)
by adding an optional `mcp:` block to `plugin.yaml`. The core plugin loader
resolves every `handler` (`module:function`, relative to the plugin package)
and registers it in-process — no network MCP transport, no extra auth.

```yaml
mcp:
  enabled: true
  tools:
    - name: list_records                 # lowercase identifier, unique per plugin
      description: List every managed DNS record.
      handler: "mcp_tools:list_records"  # module:function inside the plugin
      capability: dns_records            # a read capability (see vocabulary)
      read_only: true                    # Winky only ever exposes read-only tools
      input_schema:                      # JSON Schema for the tool arguments
        type: object
        properties: {}
        additionalProperties: false
```

Handlers are async and take the argument object produced by the LLM:

```python
# plugins/my_plugin/mcp_tools.py
async def list_records(params: dict) -> dict:
    from PVE2Services.libs.db_adapter import get_db
    rows = get_db().get_dns_records()
    return {"count": len(rows), "records": rows}
```

Rules:

- `mcp` is optional — plugins without it are unaffected.
- `handler` is resolved relative to the plugin package; a broken handler is
  logged, never fatal (the plugin still loads).
- Only `read_only: true` tools reach the assistant. Declare mutating tools with
  `read_only: false` and they will never be offered to the model.
- Tools must return JSON-serializable data; the agent serializes with
  `default=str` as a fallback.
- Read the core copy of this guide / `libs/plugin_manifest.py` for the exact
  `MCPTool`/`MCPServer` schema.


## Minimal Plugin

```python
# plugins/my_plugin/__init__.py
import logging
from fastapi import FastAPI

logger = logging.getLogger("my_plugin")


def load_plugin(app: FastAPI):
    """Load the plugin into the FastAPI application."""
    logger.info("Loading My Plugin")

    @app.get("/api/plugins/my_plugin/info")
    async def plugin_info():
        return {
            "plugin": "my_plugin",
            "name": "My Custom Plugin",
            "version": "0.1.0",
            "description": "A custom plugin example",
            "status": "active",
        }

    @app.get("/api/plugins/my_plugin/config")
    async def get_config():
        return {"configured": True, "config": {}}

    @app.post("/api/plugins/my_plugin/config")
    async def save_config():
        return {"saved": True}
```

## Plugin Discovery

Plugins are auto-discovered from the `plugins/` directory: each directory with
an `__init__.py` and a valid `plugin.yaml` is validated (schema and
`core_compat`), classified by trust tier from verified provenance, then
imported and `load_plugin(app)` is called. Loading failures are logged, never
fatal. See `libs/plugin_loader.py` and
[docs/PLUGIN_STORE.md](https://github.com/Montenigri/pve2service-core/blob/main/docs/PLUGIN_STORE.md) for the trust model and the
store distribution channel.

### Naming Convention

- Plugin directory name: lowercase with underscores (e.g., `my_plugin`)
- Plugin ID: the manifest `id` (must match the directory name)
- API prefix: `/api/plugins/{plugin_id}/`

### Plugin Order

Plugins are loaded in a defined order (see `PLUGIN_ORDER` in `main.py`). Custom plugins are loaded after built-in plugins.

## Required Endpoints

Each plugin should implement these standard endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plugins/{id}/info` | GET | Plugin metadata |
| `/api/plugins/{id}/config` | GET | Get current configuration |
| `/api/plugins/{id}/config` | POST | Save configuration |
| `/api/plugins/{id}/test` | POST | Test connection/credentials |
| `/api/plugins/{id}/sync` | POST | Trigger synchronization |

## Using Shared Libraries

### Database Access

```python
from PVE2Services.libs.db_adapter import DBAdapter, get_db

# Method 1: Direct instance (creates new engine each time)
db = DBAdapter()
settings = db.get_all_settings()

# Method 2: Thread-safe singleton (recommended)
db = get_db()
```

### Configuration Management

```python
from PVE2Services.libs.connector_config import ConnectorConfig, get_config_manager

# Method 1: Direct instance
config_manager = ConnectorConfig()
config = config_manager.get_config("my_plugin")
config_manager.save_config("my_plugin", {"key": "value"}, enabled=True)

# Method 2: Singleton (recommended)
config_manager = get_config_manager()
```

### Error Handling

```python
from PVE2Services.libs.errors import PluginError, ConfigError, ConnectorError

# Raise plugin-specific errors
raise PluginError("Something failed", plugin_id="my_plugin")

# Configuration errors return 400
raise ConfigError("Missing required field", plugin_id="my_plugin")

# Connector errors return 500
raise ConnectorError("SSH connection failed", plugin_id="my_plugin")
```

### HTTP Client

```python
from PVE2Services.libs.http import get_http_client

# Async HTTP client with connection pooling
client = await get_http_client()
response = await client.get("https://api.example.com/data")
```

### Scheduler

```python
from PVE2Services.libs.scheduler import start_scheduler, stop_scheduler, scheduler_status

# Start a background job
def my_job():
    # Your periodic task
    pass

started = start_scheduler(my_job, seconds=300)  # Every 5 minutes

# Check status
status = scheduler_status()

# Stop the scheduler
stopped = stop_scheduler()
```

## Plugin UI (Optional)

Plugins can include an HTML frontend page:

```python
# plugins/my_plugin/__init__.py
from .frontend import build_page

def load_plugin(app: FastAPI):
    @app.get("/admin/my_plugin")
    async def plugin_page():
        return HTMLResponse(content=build_page())
```

```python
# plugins/my_plugin/frontend.py
def build_page() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <head><title>My Plugin</title></head>
    <body>
        <h1>My Custom Plugin</h1>
        <div id="config-form">
            <!-- Your plugin UI here -->
        </div>
    </body>
    </html>
    """
```

## Background Tasks

For periodic operations, use the scheduler:

```python
from PVE2Services.libs.scheduler import start_scheduler

def load_plugin(app: FastAPI):
    def background_check():
        # Run periodically
        pass

    # Start scheduler when plugin loads
    start_scheduler(background_check, seconds=300)
```

## Encryption for Secrets

For storing API keys and secrets:

```python
from PVE2Services.libs.connector_config import encrypt_value, decrypt_value

# Encrypt before storing
encrypted = encrypt_value("my_api_key_12345")
config_manager.save_config("my_plugin", {"api_key": encrypted})

# Decrypt when reading
config = config_manager.get_config("my_plugin")
api_key = decrypt_value(config.get("api_key", ""))
```

## Testing Your Plugin

```python
# tests/test_my_plugin.py
import pytest
from fastapi.testclient import TestClient
from PVE2Services.core.wiki_service.app.main import app

def test_plugin_info():
    c = TestClient(app)
    r = c.get("/api/plugins/my_plugin/info")
    assert r.status_code == 200
    assert r.json()["plugin"] == "my_plugin"

def test_plugin_config():
    c = TestClient(app)
    r = c.get("/api/plugins/my_plugin/config")
    assert r.status_code == 200
```

## Audit Logging

Every plugin should record its real operations (sync, config changes,
destructive actions, CRUD) in the central audit log. Logs are human-readable,
rotated daily (`logs/audit-YYYY-MM-DD.txt`), with configurable retention
(default 30 days, changeable from the `/admin/log` page).

### Import

```python
try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None
```

Always guard the import and wrap log calls in `try/except`: a logging failure
must never break the real operation.

### Severities

| Severity  | When to use                                              |
|-----------|----------------------------------------------------------|
| `INFO`    | Operation in progress, kickoff, internal sub-step        |
| `OK`      | Operation completed successfully                         |
| `WARNING` | Non-fatal error, skipped item, missing configuration     |
| `ERROR`   | Failed operation                                         |
| `CRITICAL`| Security event or destructive action taken or attempted  |

### Single entry

```python
audit.log(plugin_id, "OK", "Sync completed", detail=f"items_synced: {items}")
```

`detail` is optional and written as an indented line under the entry.

### Nested operations (sub-operations)

Use `audit.operation(...)` as a context manager. Entries inside the context
are indented two extra spaces; nested contexts increase the indent
recursively. Multiple sub-operations run sequentially at the same level.

```python
with audit.operation(plugin_id, "INFO", "Sync started"):
    audit.log(plugin_id, "INFO", "Fetching machines...")
    for entity in entities:
        if ok:
            audit.log(plugin_id, "OK", f"Created page: {entity.name}",
                      detail=f"type: {entity.type}")
        else:
            audit.log(plugin_id, "ERROR", f"Failed page: {entity.name}",
                      detail="format error")
    audit.log(plugin_id, "OK", "Sync completed", detail=f"created: {n}")
```

### Header convention

Always pass the plugin **id in lowercase** (e.g. `pve2dns`, `example_plugin`)
in the header so it reads `[example_plugin] OK Sync completed`. Use `"core"`
for operations that belong to the core, not a plugin.

### Never log secrets

Never log token/password/webhook/SSH values. Only log keys/names and
boolean/status indicators. If you must reference a secret value, mask it:

```python
from PVE2Services.libs.audit import redact
masked = redact(secret)  # e.g. "tok_****"
```

### Example instrumented sync

```python
@app.post("/api/plugins/my_plugin/sync")
async def my_sync():
    config = config_manager.get_config("my_plugin")
    if not config.get("enabled"):
        if audit:
            audit.log("my_plugin", "WARNING", "Sync skipped",
                      detail="Plugin not enabled")
        return {"synced": False, "message": "Not enabled"}

    if audit:
        with audit.operation("my_plugin", "INFO", "Sync started"):
            created, updated = 0, 0
            for item in fetch_items():
                if upsert(item):
                    created += 1
                    audit.log("my_plugin", "OK", f"Created item {item.id}")
                else:
                    updated += 1
                    audit.log("my_plugin", "OK", f"Updated item {item.id}")
            audit.log("my_plugin", "OK", "Sync completed",
                      detail=f"created: {created}, updated: {updated}")
    return {"synced": True, "items_synced": created + updated}
```

## Best Practices

1. **Error Handling**: Always use custom exceptions from `libs/errors.py`
2. **Logging**: Use `logging.getLogger("plugin_name")` for standard logs
3. **Audit Logging**: Record every real operation with `PVE2Services.libs.audit`
4. **Configuration**: Use `ConnectorConfig` for persistent settings
5. **Database**: Use `get_db()` singleton for thread safety
6. **Secrets**: Always encrypt sensitive data with `encrypt_value()` and never
   log secret values (use `redact()`)
7. **Tests**: Write tests for your plugin endpoints
8. **Documentation**: Add a README.md in your plugin directory

## Example Plugins

See these existing plugins for reference:
- `plugins/example_plugin/` - Minimal plugin with audit logging hooks baked in
- `plugins/PVE2DNS/` - DNS record management
- `plugins/PVE2Power/` - Power schedule management
- `plugins/PVE2Proxy/` - Reverse proxy configuration
- `plugins/pve2wiki/` - Wiki.js integration
