"""PVE2Wiki — Sync Proxmox infrastructure to Wiki.js via GraphQL."""

import json
import logging
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.libs.plugin_base import get_core_machines
from PVE2Services.libs.timeutil import local_now

try:
    from PVE2Services.libs.audit import audit
except ImportError:
    audit = None

from .frontend import build_page
from .providers import (
    DEFAULT_TEMPLATES,
    TEMPLATE_FILTERS,
    TEMPLATE_VARS,
    TemplateEngine,
    WikiJsClient,
    compute_diff,
    hash_entity,
)
from .schemas import (
    SyncResult,
    SyncStatus,
    TemplateUpdate,
    WikiJsConfig,
    WikiPage,
)

logger = logging.getLogger("pve2wiki")

ENTITY_TYPES = {
    "vm": "Virtual Machines",
    "lxc": "Linux Containers",
    "node": "Nodes",
    "storage": "Storage",
    "disk": "Physical Disks",
    "cluster": "Cluster Status",
    "ceph": "Ceph Health",
    "changelog": "Changelog Page",
}


def load_plugin(app: FastAPI):
    class _LazyConfigManager:
        """Per-call ConnectorConfig so requests always bind to the live DB resolution."""

        def __getattr__(self, name):
            if ConnectorConfig is None:
                raise RuntimeError("Config manager unavailable")
            return getattr(ConnectorConfig(), name)

        def __bool__(self):
            return ConnectorConfig is not None

    config_manager = _LazyConfigManager()
    connector_id = "pve2wiki"

    @app.get("/api/plugins/pve2wiki/info")
    async def plugin_info():
        return {
            "plugin": "pve2wiki",
            "name": "PVE2 Wiki",
            "version": "0.1.0",
            "description": "Sync Proxmox machines, nodes and storage to Wiki.js",
            "status": "active",
        }

    @app.get("/api/plugins/pve2wiki/config")
    async def get_config():
        if not config_manager:
            return {"error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        sync_state = config_manager.get_sync_state(connector_id)
        db = DBAdapter()
        templates = db.get_templates()
        configured = bool(config.get("wiki_url")) and bool(config.get("wiki_token"))
        config["wiki_orphan_handling"] = db.get_setting("wiki_orphan_handling") or "recreate"
        return {
            "configured": configured,
            "config": config,
            "sync_state": sync_state,
            "templates": templates,
            "default_templates": {k: v for k, v in DEFAULT_TEMPLATES.items()},
        }

    @app.post("/api/plugins/pve2wiki/config")
    async def save_config(body: WikiJsConfig):
        if not config_manager:
            return {"error": "Config manager unavailable"}
        success = config_manager.save_config(connector_id, body.model_dump(), body.enabled)
        db = DBAdapter()
        db.set_setting("wiki_orphan_handling", body.wiki_orphan_handling)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Config saved",
                          detail=f"enabled: {body.enabled}\n"
                                 f"wiki_orphan_handling: {body.wiki_orphan_handling}")
            except Exception:
                pass
        return {"saved": success, "connector": connector_id}

    @app.post("/api/plugins/pve2wiki/test")
    async def test_connection():
        if not config_manager:
            return {"connected": False, "error": "Config manager unavailable"}
        config = config_manager.get_config(connector_id)
        if not config.get("wiki_url"):
            return {"connected": False, "error": "Wiki.js URL not configured"}
        client = WikiJsClient(config["wiki_url"], config.get("wiki_token", ""))
        try:
            result = await client.test()
            return result
        finally:
            await client.close()

    @app.get("/api/plugins/pve2wiki/templates")
    async def list_templates():
        db = DBAdapter()
        stored = db.get_templates()
        result = {}
        for ttype, label in ENTITY_TYPES.items():
            result[ttype] = {"label": label, "content": stored.get(ttype, DEFAULT_TEMPLATES.get(ttype, ""))}
        return {"templates": result, "variables": TEMPLATE_VARS, "filters": TEMPLATE_FILTERS}

    @app.put("/api/plugins/pve2wiki/templates/{type_key}")
    async def save_template(type_key: str, body: TemplateUpdate):
        if type_key not in ENTITY_TYPES:
            return {"error": f"Unknown type: {type_key}, must be one of {list(ENTITY_TYPES.keys())}"}
        db = DBAdapter()
        db.save_template(type_key, body.content)
        if audit:
            try:
                audit.log(connector_id, "INFO", "Template saved",
                          detail=f"type: {type_key}")
            except Exception:
                pass
        return {"status": "ok", "type": type_key}

    @app.post("/api/plugins/pve2wiki/templates/reset")
    async def reset_templates():
        db = DBAdapter()
        for ttype in ENTITY_TYPES:
            if ttype in DEFAULT_TEMPLATES:
                db.save_template(ttype, DEFAULT_TEMPLATES[ttype])
        if audit:
            try:
                audit.log(connector_id, "INFO", "All templates reset to defaults",
                          detail=f"types: {', '.join(ENTITY_TYPES.keys())}")
            except Exception:
                pass
        return {"status": "ok", "reset": list(ENTITY_TYPES.keys())}

    def _content_types(value) -> str:
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value or "")

    async def _fetch_entity_data(config: dict) -> list:
        base_path = config.get("base_path", "/infrastructure/proxmox").strip("/")
        db = DBAdapter()
        entities = []

        for m in await get_core_machines():
            m["entity_type"] = m.get("type", "vm")
            m["entity_path"] = f"{base_path}/{m['entity_type']}/{m['id']}"
            entities.append(m)

        # Nodes and storage come straight from Proxmox using the global
        # settings (mirrored by PVE2Core on setup) instead of HTTP self-calls,
        # which fail with 401 under the auth middleware.
        from PVE2Services.core.wiki_service.app.proxmox_adapter import create_client_if_possible

        client = await create_client_if_possible(None, None, None)
        if client:
            try:
                for n in await client.get_nodes():
                    n["entity_type"] = "node"
                    n["entity_path"] = f"{base_path}/node/{n['id']}"
                    entities.append(n)

                storage = await client.get_storage()
                for s in storage:
                    s["entity_type"] = "storage"
                    s["entity_path"] = f"{base_path}/storage/{s['id']}"
                    entities.append(s)
                    # Storage usage over time
                    try:
                        db.save_storage_history(
                            node=s.get("node", ""),
                            storage_name=s.get("name", ""),
                            total_bytes=s.get("total_disk") or 0,
                            used_bytes=s.get("used_disk") or 0,
                            content_types=_content_types(s.get("content")),
                        )
                    except Exception:
                        logger.exception("Failed to record storage history")

                if config.get("include_disks"):
                    disks = await client.get_disks()
                    for d in disks:
                        d["entity_type"] = "disk"
                        d["entity_path"] = f"{base_path}/disk/{d['id']}"
                        entities.append(d)
                        # SMART health over time
                        try:
                            db.save_health_history(
                                component="disk",
                                item_id=f"{d.get('node', '')}:{d.get('name', '')}",
                                status=d.get("status") or "UNKNOWN",
                                details=json.dumps(
                                    {"model": d.get("model"), "serial": d.get("serial")},
                                    default=str,
                                ),
                            )
                        except Exception:
                            logger.exception("Failed to record disk health history")

                if config.get("include_cluster"):
                    summary = await client.get_cluster_summary()
                    if summary:
                        summary["entity_type"] = "cluster"
                        summary["entity_path"] = f"{base_path}/cluster/{summary['id']}"
                        entities.append(summary)

                if config.get("include_ceph"):
                    ceph = await client.get_ceph_health()
                    if ceph:
                        ceph["entity_type"] = "ceph"
                        ceph["entity_path"] = f"{base_path}/ceph/{ceph['id']}"
                        entities.append(ceph)
                        try:
                            db.save_health_history(
                                component="ceph",
                                item_id=ceph.get("id", "ceph-cluster"),
                                status=ceph.get("status") or "UNKNOWN",
                                details=str(ceph.get("details") or ""),
                            )
                        except Exception:
                            logger.exception("Failed to record ceph health history")
            finally:
                await client.close()

        return entities

    @app.get("/api/plugins/pve2wiki/entities")
    async def list_entities():
        """Return all entities (machines, nodes, storage) with their wiki status."""
        config = config_manager.get_config(connector_id) if config_manager else {}
        entities = await _fetch_entity_data(config)
        db = DBAdapter()
        wiki_pages = {p["entity_id"]: p for p in db.get_wiki_pages()}

        result = []
        for e in entities:
            eid = str(e.get("id", ""))
            saved = wiki_pages.get(eid)
            result.append({
                "entity_id": eid,
                "entity_type": e.get("entity_type", ""),
                "name": e.get("name", ""),
                "node": e.get("node", ""),
                "status": e.get("status", ""),
                "wiki_path": saved["wiki_path"] if saved else e.get("entity_path", ""),
                "last_synced": saved.get("last_synced") if saved else None,
            })
        return {"entities": result, "total": len(result)}

    def _entity_snapshot(state: dict):
        """Parse the stored entity JSON snapshot from a sync_state row."""
        raw = state.get("entity_data")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    @app.post("/api/plugins/pve2wiki/sync", response_model=SyncResult)
    async def trigger_sync():
        if not config_manager:
            return SyncResult(status="error", errors=["Config manager unavailable"])
        config = config_manager.get_config(connector_id)
        if not config.get("enabled") or not config.get("wiki_url"):
            return SyncResult(status="error", errors=["Wiki.js not configured — set the URL and API token in Config"])

        db = DBAdapter()
        locale = config.get("locale", "en")
        base_path = config.get("base_path", "/infrastructure/proxmox").strip("/")

        templates = db.get_templates()
        engine = TemplateEngine(templates, history_fn=lambda eid: db.get_entity_changes(eid, 10))
        entities = await _fetch_entity_data(config)
        client = WikiJsClient(config["wiki_url"], config.get("wiki_token", ""))
        wiki_pages_db = {p["entity_id"]: p for p in db.get_wiki_pages()}
        states: dict = {}
        for st in db.get_all_sync_states():
            states[str(st["id"])] = st

        created = 0
        updated = 0
        archived_count = 0
        errors: list[str] = []
        details: list[WikiPage] = []

        try:
            for e in entities:
                eid = str(e.get("id", ""))
                etype = e.get("entity_type", "vm")
                title = e.get("name", eid)
                path = e.get("entity_path") or f"{base_path}/{etype}/{eid}"
                ch = hash_entity(e)

                state = states.get(eid)
                needs_create = (not state) or bool(state.get("archived"))
                needs_update = (not needs_create) and state.get("hash") != ch

                if not needs_create and not needs_update:
                    continue

                # Prepare the current change entry BEFORE rendering, so the
                # page's Change History section includes this very change.
                if needs_create:
                    action = "created"
                    entry_details = "Created wiki page"
                else:
                    action = "updated"
                    entry_details = compute_diff(_entity_snapshot(state), e)
                pending_entry = {
                    "timestamp": local_now(),
                    "action": action,
                    "details": entry_details,
                }
                engine.set_pending_history(eid, pending_entry)

                try:
                    content = engine.render(etype, e)

                    if needs_create:
                        existing = await client.find_page_by_path(path, locale)
                        if existing:
                            await client.update_page(existing["id"], path, title, content, locale)
                            db.upsert_wiki_page(eid, etype, path, existing["id"], title, ch)
                            updated += 1
                        else:
                            result = await client.create_page(
                                path, title, content, locale,
                                tags=[etype, "pve2wiki"],
                            )
                            db.upsert_wiki_page(eid, etype, path, result.get("id", 0), title, ch)
                            created += 1
                    else:
                        saved = wiki_pages_db.get(eid) or {}
                        page_id = saved.get("wiki_page_id") or 0
                        if page_id:
                            await client.update_page(page_id, path, title, content, locale)
                        else:
                            existing = await client.find_page_by_path(path, locale)
                            if existing:
                                await client.update_page(existing["id"], path, title, content, locale)
                                page_id = existing["id"]
                            else:
                                result = await client.create_page(
                                    path, title, content, locale,
                                    tags=[etype, "pve2wiki"],
                                )
                                page_id = result.get("id", 0)
                        db.upsert_wiki_page(eid, etype, path, page_id, title, ch)
                        updated += 1

                    # Persist history entry and snapshot only after a successful push,
                    # so a failed upload never leaves phantom/duplicated entries.
                    db.save_changelog(action, etype, eid, title, entry_details)
                    db.update_sync_state({
                        "id": eid,
                        "type": etype,
                        "hash": ch,
                        "wiki_path": path,
                        "archived": False,
                        "entity_data": e,
                    })
                    details.append(WikiPage(path=path, title=title, content=content, entity_type=etype, entity_id=eid, synced=True))
                except Exception as ex:
                    errors.append(f"{eid} ({title}): {ex}")
                    details.append(WikiPage(path=path, title=title, content=content, entity_type=etype, entity_id=eid, synced=False))
                finally:
                    engine.set_pending_history(eid, None)

            # Archive entities that disappeared from Proxmox
            current_ids = {str(e.get("id")) for e in entities}
            date_suffix = datetime.now().strftime("%Y-%m-%d")
            for sid, state in states.items():
                if sid in current_ids or state.get("archived"):
                    continue
                old_page = wiki_pages_db.get(sid) or {}
                page_id = old_page.get("wiki_page_id") or 0
                old_path = state.get("wiki_path") or old_page.get("wiki_path") or ""
                if not page_id or not old_path:
                    continue
                extract_name = old_path.rstrip("/").split("/")[-1]
                stype = state.get("type") or "entity"
                archive_path = f"{base_path}/archive/{stype}/{extract_name} - {date_suffix}"
                try:
                    await client.move_page(page_id, archive_path, locale)
                    new_state = dict(state)
                    new_state["archived"] = True
                    new_state["wiki_path"] = archive_path
                    db.update_sync_state(new_state)
                    db.save_changelog("deleted", str(stype), sid, old_page.get("title") or sid, f"Moved to archive ({archive_path})")
                    archived_count += 1
                except Exception as ex:
                    errors.append(f"archive {sid}: {ex}")

            # Changelog wiki page (update-or-create at <base>/changelog)
            try:
                entries = db.get_changelog(50)
                changelog_content = engine.render_changelog(entries)
                changelog_path = f"{base_path}/changelog"
                existing = await client.find_page_by_path(changelog_path, locale)
                if existing:
                    await client.update_page(existing["id"], changelog_path, "Changelog", changelog_content, locale)
                else:
                    await client.create_page(changelog_path, "Changelog", changelog_content, locale, tags=["pve2wiki"])
            except Exception as ex:
                errors.append(f"changelog page: {ex}")

            status = "error" if errors and not (created or updated or archived_count) else "success"
            config_manager.update_sync_state(connector_id, status, items_synced=created + updated + archived_count)
            if audit:
                try:
                    sev = "OK" if status == "success" else "WARNING"
                    audit.log(connector_id, sev, "Wiki sync completed",
                              detail=f"entities_fetched: {len(entities)}\n"
                                     f"pages_created: {created}\n"
                                     f"pages_updated: {updated}\n"
                                     f"pages_archived: {archived_count}\n"
                                     f"errors: {len(errors)}")
                except Exception:
                    pass
            return SyncResult(status=status, created=created, updated=updated,
                              archived=archived_count, errors=errors, details=details)
        finally:
            await client.close()

    @app.get("/api/plugins/pve2wiki/pages")
    async def list_synced_pages():
        db = DBAdapter()
        pages = db.get_wiki_pages()
        return {"pages": pages, "total": len(pages)}

    @app.get("/api/plugins/pve2wiki/status", response_model=SyncStatus)
    async def sync_status():
        if not config_manager:
            return SyncStatus()
        sync_state = config_manager.get_sync_state(connector_id)
        db = DBAdapter()
        pages = db.get_wiki_pages()
        return SyncStatus(
            total_pages=len(pages),
            last_sync=next(
                (s.get("last_sync_at") for s in [sync_state] if s.get("last_sync_at")),
                None,
            ),
            last_status=sync_state.get("last_sync_status", "pending") if sync_state else "pending",
        )

    @app.get("/admin/pve2wiki", response_class=HTMLResponse)
    async def admin_page():
        configured = False
        if config_manager:
            cfg = config_manager.get_config(connector_id)
            configured = bool(cfg.get("wiki_url")) and bool(cfg.get("wiki_token"))
        return HTMLResponse(content=build_page(configured=configured))
