"""Example Plugin — demonstrates how to build a PVE2Services plugin.

This plugin shows:
- Standard endpoint structure (/info, /config, /test, /sync)
- Using ConnectorConfig for persistent configuration
- Using DBAdapter for data storage
- Audit logging hooks (libs.audit)
- Error handling with custom exceptions
- Basic CRUD operations
"""

import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None
from PVE2Services.libs.errors import PluginError

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

logger = logging.getLogger("example_plugin")

PLUGIN_ID = "example_plugin"


def load_plugin(app: FastAPI):
    """Load the example plugin into the FastAPI application."""
    config_manager = None
    if ConnectorConfig:
        try:
            config_manager = ConnectorConfig()
        except Exception:
            logger.warning("ConnectorConfig unavailable")

    if audit:
        try:
            audit.log(PLUGIN_ID, "OK", "Plugin loaded")
        except Exception:
            pass

    @app.get(f"/api/plugins/{PLUGIN_ID}/info")
    async def plugin_info():
        return {
            "plugin": PLUGIN_ID,
            "name": "Example Plugin",
            "version": "0.1.0",
            "description": "A demo plugin showing how to build PVE2Services plugins",
            "status": "active",
        }

    @app.get(f"/api/plugins/{PLUGIN_ID}/config")
    async def get_config():
        if not config_manager:
            return {"configured": False, "config": {}, "error": "Config manager unavailable"}
        config = config_manager.get_config(PLUGIN_ID)
        sync_state = config_manager.get_sync_state(PLUGIN_ID)
        configured = bool(config.get("api_endpoint"))
        return {"configured": configured, "config": config, "sync_state": sync_state}

    @app.post(f"/api/plugins/{PLUGIN_ID}/config")
    async def save_config(body: dict):
        if not config_manager:
            raise PluginError("Config manager unavailable", plugin_id=PLUGIN_ID)

        if audit:
            try:
                keys_saved = list(body.keys())
                with audit.operation(PLUGIN_ID, "INFO", "Config saved",
                                     detail=f"Keys: {', '.join(keys_saved)}"):
                    if body.get("enabled"):
                        audit.log(PLUGIN_ID, "INFO", "Connector enabled")
                    else:
                        audit.log(PLUGIN_ID, "INFO", "Connector disabled")
            except Exception:
                pass

        success = config_manager.save_config(PLUGIN_ID, body, body.get("enabled", False))
        return {"saved": success, "connector": PLUGIN_ID}

    @app.post(f"/api/plugins/{PLUGIN_ID}/test")
    async def test_connection():
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        config = config_manager.get_config(PLUGIN_ID)
        endpoint = config.get("api_endpoint", "")
        if not endpoint:
            if audit:
                try:
                    audit.log(PLUGIN_ID, "WARNING", "Connection test skipped",
                              detail="api_endpoint not configured")
                except Exception:
                    pass
            return {"connected": False, "error": "API endpoint not configured"}

        if audit:
            try:
                with audit.operation(PLUGIN_ID, "INFO", "Connection test",
                                     detail=f"endpoint: {endpoint}"):
                    pass
            except Exception:
                pass

        # In a real plugin, you would test the connection here
        if audit:
            try:
                audit.log(PLUGIN_ID, "OK", "Connection successful",
                          detail=f"endpoint: {endpoint}")
            except Exception:
                pass
        return {"connected": True, "message": f"Connection to {endpoint} successful"}

    @app.post(f"/api/plugins/{PLUGIN_ID}/sync")
    async def run_sync():
        if not config_manager:
            raise PluginError("Config manager unavailable", plugin_id=PLUGIN_ID)
        config = config_manager.get_config(PLUGIN_ID)
        if not config.get("enabled"):
            if audit:
                try:
                    audit.log(PLUGIN_ID, "WARNING", "Sync skipped",
                              detail="Plugin not enabled")
                except Exception:
                    pass
            return {"synced": False, "message": "Plugin not enabled"}

        if audit:
            try:
                with audit.operation(PLUGIN_ID, "INFO", "Sync started"):
                    audit.log(PLUGIN_ID, "INFO", "Fetching data from external source...")
            except Exception:
                pass

        # Example: fetch data and store in DB
        # In a real plugin, you would fetch from an external API
        items_synced = 0
        config_manager.update_sync_state(PLUGIN_ID, "success", items_synced=items_synced)

        if audit:
            try:
                audit.log(PLUGIN_ID, "OK", "Sync completed",
                          detail=f"items_synced: {items_synced}")
            except Exception:
                pass

        return {"synced": True, "items_synced": items_synced}

    @app.get(f"/admin/{PLUGIN_ID}", response_class=HTMLResponse)
    async def plugin_page():
        return HTMLResponse(content=_build_page())


def _build_page() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Example Plugin - PVE2Services</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               max-width: 800px; margin: 40px auto; padding: 20px; background: #f5f5f5; }
        .card { background: white; border-radius: 8px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-bottom: 8px; }
        .subtitle { color: #666; margin-bottom: 24px; }
        .status { padding: 8px 16px; border-radius: 4px; display: inline-block; }
        .status-ok { background: #d4edda; color: #155724; }
        .status-error { background: #f8d7da; color: #721c24; }
        button { background: #007bff; color: white; border: none; padding: 10px 20px; 
                 border-radius: 4px; cursor: pointer; margin-right: 10px; }
        button:hover { background: #0056b3; }
        .info { background: #e7f3ff; padding: 16px; border-radius: 4px; margin-top: 16px; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
    <div class="card">
        <a href="/admin/hub" style="color:#667eea;text-decoration:none;margin-bottom:16px;display:inline-block;">← Back to Hub</a>
        <h1>Example Plugin</h1>
        <p class="subtitle">A demo plugin showing how to build PVE2Services plugins</p>
        
        <div id="status">
            <span class="status status-ok">Active</span>
        </div>
    </div>
    
    <div class="card">
        <h2>Configuration</h2>
        <p>This is a demo configuration form.</p>
        
        <div class="info">
            <strong>Plugin ID:</strong> <code>example_plugin</code><br>
            <strong>API Prefix:</strong> <code>/api/plugins/example_plugin/</code>
        </div>
        
        <div style="margin-top: 20px;">
            <button onclick="testConnection()">Test Connection</button>
            <button onclick="runSync()">Run Sync</button>
        </div>
        
        <div id="result" style="margin-top: 16px;"></div>
    </div>
    
    <div class="card">
        <h2>Plugin Development</h2>
        <p>To create your own plugin:</p>
        <ol>
            <li>Create a directory under <code>plugins/</code></li>
            <li>Add an <code>__init__.py</code> with a <code>load_plugin(app)</code> function</li>
            <li>Implement the standard endpoints</li>
            <li>Add audit logging hooks (see <a href="/admin/log">audit logs</a>)</li>
            <li>Restart the application</li>
        </ol>
        <p>See <a href="/admin/hub">Plugin Hub</a> for more information.</p>
    </div>
    
    <script>
        async function testConnection() {
            const result = document.getElementById('result');
            result.innerHTML = 'Testing connection...';
            try {
                const r = await fetch('/api/plugins/example_plugin/test', { method: 'POST' });
                const data = await r.json();
                result.innerHTML = data.connected 
                    ? '<span class="status status-ok">' + data.message + '</span>'
                    : '<span class="status status-error">' + data.error + '</span>';
            } catch (e) {
                result.innerHTML = '<span class="status status-error">Error: ' + e.message + '</span>';
            }
        }
        
        async function runSync() {
            const result = document.getElementById('result');
            result.innerHTML = 'Running sync...';
            try {
                const r = await fetch('/api/plugins/example_plugin/sync', { method: 'POST' });
                const data = await r.json();
                result.innerHTML = data.synced
                    ? '<span class="status status-ok">Synced ' + data.items_synced + ' items</span>'
                    : '<span class="status status-error">' + data.message + '</span>';
            } catch (e) {
                result.innerHTML = '<span class="status status-error">Error: ' + e.message + '</span>';
            }
        }
    </script>
</body>
</html>"""