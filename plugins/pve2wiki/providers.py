"""Wiki.js GraphQL client and template renderer."""

import hashlib
import logging
from typing import Any, Dict, Optional

import httpx
from jinja2 import BaseLoader, ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

logger = logging.getLogger("pve2wiki.providers")

DEFAULT_TEMPLATES = {    "vm": (
        "# {{ name }}\n\n"
        "## Overview\n"
        "- **ID:** `{{ id }}`\n"
        "- **Node:** {{ node }}\n"
        "- **Status:** {{ status }}\n"
        "- **Type:** Virtual Machine\n\n"
        "## Resources\n"
        "- **vCPUs:** {{ cores }}\n"
        "- **Memory:** {{ memory_mb | format_mb }}\n"
        "- **Disk:** {{ disk_gb }} GB\n\n"
        "## Network\n"
        "- **IP Addresses:**{% for ip in ip_addresses %}\n  - `{{ ip }}`{% else %}\n  - *None*{% endfor %}\n\n"
        "## Tags\n"
        "{% for tag in tags %}`{{ tag }}` {% else %}*No tags*{% endfor %}\n\n"
        "## Change History\n"
        "{{ id | entity_history }}"
    ),
    "lxc": (
        "# {{ name }}\n\n"
        "## Overview\n"
        "- **ID:** `{{ id }}`\n"
        "- **Node:** {{ node }}\n"
        "- **Status:** {{ status }}\n"
        "- **Type:** Linux Container\n\n"
        "## Resources\n"
        "- **vCPUs:** {{ cores }}\n"
        "- **Memory:** {{ memory_mb | format_mb }}\n"
        "- **Disk:** {{ disk_gb }} GB\n\n"
        "## Network\n"
        "- **IP Addresses:**{% for ip in ip_addresses %}\n  - `{{ ip }}`{% else %}\n  - *None*{% endfor %}\n\n"
        "## Tags\n"
        "{% for tag in tags %}`{{ tag }}` {% else %}*No tags*{% endfor %}\n\n"
        "## Change History\n"
        "{{ id | entity_history }}"
    ),
    "node": (
        "# {{ name }}\n\n"
        "## Overview\n"
        "- **Node:** {{ name }}\n"
        "- **Status:** {{ status }}\n"
        "- **Memory:** {{ memory_mb | format_mb }}\n"
        "- **CPU Cores:** {{ maxcpu }}\n"
        "- **CPU Load:** {{ cpu_load | round(2) }}\n"
        "- **Uptime:** {{ uptime_sec | format_uptime }}\n\n"
        "## Change History\n"
        "{{ id | entity_history }}"
    ),
    "storage": (
        "# {{ name }}\n\n"
        "## Overview\n"
        "- **Name:** {{ name }}\n"
        "- **Node:** {{ node }}\n"
        "- **Type:** {{ type }}\n"
        "- **Total:** {{ total_gb }} GB\n"
        "- **Used:** {{ used_gb }} GB\n"
        "- **Content:** {{ content }}\n\n"
        "## Change History\n"
        "{{ id | entity_history }}"
    ),
    "disk": (
        "# {{ name }} ({{ node }})\n\n"
        "## Overview\n"
        "- **Device:** {{ name }}\n"
        "- **Node:** {{ node }}\n"
        "- **Kind:** {{ disk_type | default('-') }}\n"
        "- **Model:** {{ model | default('-') }}\n"
        "- **Serial:** {{ serial | default('-') }}\n"
        "- **Size:** {{ size_bytes | format_size }}\n"
        "- **Health:** {{ status }}\n\n"
        "## Change History\n"
        "{{ id | entity_history }}"
    ),
    "cluster": (
        "# Cluster {{ name }}\n\n"
        "## Overview\n"
        "- **Status:** {{ status }}\n"
        "- **Nodes:** {{ nodes_count }}\n"
        "- **Quorum:** {{ quorate }}\n\n"
        "## Change History\n"
        "{{ id | entity_history }}"
    ),
    "ceph": (
        "# Ceph Health\n\n"
        "## Overview\n"
        "- **Status:** {{ status }}\n"
        "- **OSDs:** {{ osd_total }} ({{ osd_in }} in / {{ osd_up }} up)\n"
        "- **Monitors:** {{ mon_count }}\n\n"
        "## Details\n"
        "{{ details }}\n\n"
        "## Change History\n"
        "{{ id | entity_history }}"
    ),
    "changelog": (
        "# Changelog\n\n"
        "| Date | Action | Type | Name | Details |\n"
        "|------|--------|------|------|---------|\n"
        "{% for e in entries %}| {{ e.timestamp }} | {{ e.action }} | {{ e.entity_type }} "
        "| {{ e.entity_name }} | {{ e.details or '' }} |\n{% endfor %}"
    ),
}

# Documented in the Templates tab: variables available to each template type.
# Keep in sync with the entity dicts built by the sync pipeline.
TEMPLATE_FILTERS = [
    {"name": "format_mb", "example": "{{ memory_mb | format_mb }}",
     "description": "Megabytes -> human size (2048 -> \"2.0 GB\")"},
    {"name": "format_size", "example": "{{ size_bytes | format_size }}",
     "description": "Bytes -> human size (1073741824 -> \"1.00 GB\")"},
    {"name": "format_uptime", "example": "{{ uptime_sec | format_uptime }}",
     "description": "Seconds -> human uptime (90061 -> \"1d 1h 1m\")"},
    {"name": "entity_history", "example": "{{ id | entity_history }}",
     "description": "Markdown bullet list of the last 10 changes for this entity"},
    {"name": "pci_main_devices", "example": "{% for d in hardware_info.pci | pci_main_devices %}{{ d.device_name }}{% endfor %}",
     "description": "Node PCI devices with a known name (GPUs, NICs...)"},
    {"name": "pci_other_devices", "example": "{% for d in hardware_info.pci | pci_other_devices %}{{ d.id }}{% endfor %}",
     "description": "Node PCI devices without a name"},
    {"name": "round(2)", "example": "{{ cpu_load | round(2) }}",
     "description": "Built-in Jinja2 filter — round a number"},
]

_TEMPLATE_COMMON = [
    {"name": "name", "description": "Display name"},
    {"name": "id", "description": "Proxmox ID (VMID for machines)"},
    {"name": "node", "description": "Host node name"},
    {"name": "status", "description": "running / stopped (machines), online / active (nodes, storage)"},
    {"name": "type", "description": "vm / lxc / node / storage"},
    {"name": "entity_path", "description": "Page path in the wiki (e.g. infrastructure/proxmox/vm/101)"},
]

TEMPLATE_VARS = {
    "vm": {"label": "Virtual Machines", "variables": _TEMPLATE_COMMON + [
        {"name": "cores", "description": "Assigned vCPUs"},
        {"name": "memory_mb", "description": "Assigned memory in MB"},
        {"name": "used_mem_mb", "description": "Used memory in MB (running machines)"},
        {"name": "disk_gb", "description": "Disk size in GB"},
        {"name": "used_disk_gb", "description": "Used disk in GB"},
        {"name": "uptime_sec", "description": "Uptime in seconds (0 when stopped)"},
        {"name": "ip_addresses", "description": "List of IPs — loop: {% for ip in ip_addresses %} ... {% endfor %} (guest agent)"},
        {"name": "tags", "description": "List of tags — loop: {% for tag in tags %} ... {% endfor %}"},
    ]},
    "lxc": {"label": "Linux Containers", "variables": _TEMPLATE_COMMON + [
        {"name": "cores", "description": "Assigned vCPUs"},
        {"name": "memory_mb", "description": "Assigned memory in MB"},
        {"name": "used_mem_mb", "description": "Used memory in MB (running machines)"},
        {"name": "disk_gb", "description": "Disk size in GB"},
        {"name": "used_disk_gb", "description": "Used disk in GB"},
        {"name": "uptime_sec", "description": "Uptime in seconds (0 when stopped)"},
        {"name": "ip_addresses", "description": "List of IPs — loop: {% for ip in ip_addresses %} ... {% endfor %} (guest agent)"},
        {"name": "tags", "description": "List of tags — loop: {% for tag in tags %} ... {% endfor %}"},
    ]},
    "node": {"label": "Nodes", "variables": _TEMPLATE_COMMON + [
        {"name": "maxcpu", "description": "CPU cores of the node"},
        {"name": "cpu_load", "description": "Current CPU usage as fraction (0..1)"},
        {"name": "uptime_sec", "description": "Node uptime in seconds — use | format_uptime"},
        {"name": "memory_mb", "description": "Total memory in MB — use | format_mb"},
        {"name": "hardware_info", "description": "Nested object: hardware_info.networks, hardware_info.pci"},
    ]},
    "storage": {"label": "Storage", "variables": _TEMPLATE_COMMON + [
        {"name": "total_gb", "description": "Total size in GB"},
        {"name": "used_gb", "description": "Used space in GB"},
        {"name": "total_disk", "description": "Total size in bytes"},
        {"name": "used_disk", "description": "Used space in bytes"},
        {"name": "content", "description": "Allowed content types (e.g. images,iso,backup)"},
    ]},
    "disk": {"label": "Physical Disks", "variables": _TEMPLATE_COMMON + [
        {"name": "model", "description": "Disk model string"},
        {"name": "serial", "description": "Serial number"},
        {"name": "disk_type", "description": "ssd / hdd / nvme"},
        {"name": "size_bytes", "description": "Size in bytes — use | format_size"},
        {"name": "status", "description": "SMART health (OK / FAILED...)"},
    ]},
    "cluster": {"label": "Cluster Status", "variables": _TEMPLATE_COMMON + [
        {"name": "nodes_count", "description": "Number of cluster members"},
        {"name": "quorate", "description": "Quorum state (yes/no)"},
    ]},
    "ceph": {"label": "Ceph Health", "variables": [
        {"name": "name", "description": "Always 'Ceph'"},
        {"name": "id", "description": "Entity id ('ceph-health')"},
        {"name": "status", "description": "HEALTH_OK / HEALTH_WARN / HEALTH_ERR"},
        {"name": "osd_total", "description": "Total OSD count"},
        {"name": "osd_in", "description": "In OSDs"},
        {"name": "osd_up", "description": "Up OSDs"},
        {"name": "mon_count", "description": "Monitor count"},
        {"name": "details", "description": "Human-readable health summary"},
    ]},
}


def format_bytes(mb: int) -> str:
    if not mb:
        return "0 B"
    b = mb * 1024 * 1024
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    size = float(b)
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    if unit == 0:
        return f"{size:.0f} {units[unit]}"
    return f"{size:.2f} {units[unit]}"


def format_size(b: int) -> str:
    """Human-readable size from raw bytes (disks, storage)."""
    if not b:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit = 0
    size = float(b)
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    if unit == 0:
        return f"{size:.0f} {units[unit]}"
    return f"{size:.2f} {units[unit]}"


def format_uptime(sec: int) -> str:
    if not sec:
        return "0s"
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    minutes, sec = divmod(sec, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if sec or not parts:
        parts.append(f"{sec}s")
    return " ".join(parts)


class WikiJsClient:
    """Client for Wiki.js GraphQL API."""

    def __init__(self, url: str, token: str, timeout: int = 15):
        self.graphql_url = url.rstrip("/")
        if "/graphql" not in self.graphql_url:
            self.graphql_url += "/graphql"
        self.token = token
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    async def _query(self, query: str, variables: dict = None) -> dict:
        resp = await self.client.post(
            self.graphql_url,
            json={"query": query, "variables": variables or {}},
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(data["errors"][0]["message"])
        return data.get("data", {})

    async def test(self) -> dict:
        q = "{ pages { list { id } } }"
        try:
            data = await self._query(q)
            return {"connected": True, "pages": len(data.get("pages", {}).get("list", []))}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def find_page_by_path(self, path: str, locale: str = "en") -> Optional[dict]:
        q = """
        query($path: String!, $locale: String!) {
          pages {
            singleByPath(path: $path, locale: $locale) {
              id, path, title, updatedAt
            }
          }
        }
        """
        try:
            data = await self._query(q, {"path": path, "locale": locale})
            page = data.get("pages", {}).get("singleByPath")
            return page or None
        except Exception:
            return None

    async def create_page(self, path: str, title: str, content: str,
                          locale: str = "en", tags: list[str] = None) -> dict:
        # Wiki.js 2.5+: page mutations live under `pages`, not at the root.
        q = """
        mutation($content: String!, $title: String!, $path: String!,
                 $locale: String!, $tags: [String]!, $isPublished: Boolean!,
                 $description: String!) {
          pages {
            create(
              content: $content, title: $title, path: $path,
              locale: $locale, tags: $tags, isPublished: $isPublished,
              editor: "markdown", isPrivate: false, description: $description
            ) {
              responseResult { succeeded errorCode slug message }
              page { id, path, title }
            }
          }
        }
        """
        data = await self._query(q, {
            "content": content,
            "title": title,
            "path": path,
            "locale": locale,
            "tags": tags or [],
            "isPublished": True,
            "description": "",
        })
        result = data.get("pages", {}).get("create", {})
        rr = result.get("responseResult", {})
        if rr and not rr.get("succeeded"):
            raise RuntimeError(f"Wiki.js createPage failed: {rr.get('message') or rr.get('slug')}")
        return result.get("page", {})

    async def update_page(self, page_id: int, path: str, title: str,
                          content: str, locale: str = "en", tags: list[str] = None) -> dict:
        q = """
        mutation($id: Int!, $content: String!, $title: String!,
                 $path: String!, $locale: String!, $description: String!,
                 $tags: [String]!) {
          pages {
            update(
              id: $id, content: $content, title: $title, path: $path,
              locale: $locale, editor: "markdown", isPublished: true,
              isPrivate: false, description: $description, tags: $tags
            ) {
              responseResult { succeeded errorCode slug message }
              page { id, path, title }
            }
          }
        }
        """
        data = await self._query(q, {
            "id": page_id,
            "content": content,
            "title": title,
            "path": path,
            "locale": locale,
            "description": "",
            "tags": tags or [],
        })
        result = data.get("pages", {}).get("update", {})
        rr = result.get("responseResult", {})
        if rr and not rr.get("succeeded"):
            raise RuntimeError(f"Wiki.js updatePage failed: {rr.get('message') or rr.get('slug')}")
        return result.get("page", {})

    async def move_page(self, page_id: int, new_path: str, locale: str = "en") -> dict:
        q = """
        mutation($id: Int!, $path: String!, $locale: String!) {
          pages {
            move(id: $id, destinationPath: $path, destinationLocale: $locale) {
              responseResult { succeeded errorCode slug message }
            }
          }
        }
        """
        data = await self._query(q, {"id": page_id, "path": new_path, "locale": locale})
        result = data.get("pages", {}).get("move", {})
        rr = result.get("responseResult", {})
        if rr and not rr.get("succeeded"):
            raise RuntimeError(f"Wiki.js movePage failed: {rr.get('message') or rr.get('slug')}")
        return result

    async def delete_page(self, page_id: int) -> dict:
        q = """
        mutation($id: Int!) {
          pages {
            delete(id: $id) {
              responseResult { succeeded errorCode slug message }
            }
          }
        }
        """
        data = await self._query(q, {"id": page_id})
        result = data.get("pages", {}).get("delete", {})
        rr = result.get("responseResult", {})
        if rr and not rr.get("succeeded"):
            raise RuntimeError(f"Wiki.js deletePage failed: {rr.get('message') or rr.get('slug')}")
        return result

    async def close(self):
        await self.client.aclose()


class TemplateEngine:
    """Renders Jinja2 templates from stored/default templates with entity data."""

    def __init__(self, stored_templates: Dict[str, str],
                 history_fn: Optional[callable] = None):
        env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
        env.filters["format_mb"] = format_bytes
        env.filters["format_size"] = format_size
        env.filters["format_uptime"] = format_uptime
        env.filters["entity_history"] = self._entity_history
        env.filters["pci_main_devices"] = _pci_main_devices
        env.filters["pci_other_devices"] = _pci_other_devices
        self.env = env
        self.history_fn = history_fn
        self.templates: Dict[str, str] = {}
        for key, default in DEFAULT_TEMPLATES.items():
            self.templates[key] = stored_templates.get(key, default)
        self._pending_history: Optional[tuple] = None

    def set_pending_history(self, entity_id: str, entry: Optional[Dict[str, Any]]):
        """Render {{ id | entity_history }} including a not-yet-persisted change."""
        self._pending_history = (str(entity_id), entry) if entry else None

    def _entity_history(self, entity_id) -> str:
        entries: list = []
        if self.history_fn:
            try:
                entries = list(self.history_fn(str(entity_id)))
            except Exception:
                logger.exception("entity_history lookup failed for %s", entity_id)
        if self._pending_history and self._pending_history[0] == str(entity_id):
            entries.insert(0, self._pending_history[1])
        if not entries:
            return "*No changes recorded yet.*"
        lines = []
        for e in entries[:10]:
            ts = str(e.get("timestamp") or "")[:10]
            action = (e.get("action") or "").lower()
            details = (e.get("details") or "").strip()
            if action == "created":
                text = "Created"
            elif action == "deleted":
                text = "Deleted (archived)"
            else:
                text = details or "Updated wiki page"
            lines.append(f"- **{ts}**: {text}")
        return "\n".join(lines)

    def render(self, entity_type: str, data: Dict[str, Any]) -> str:
        tpl_str = self.templates.get(entity_type, "# {{ name }}")
        tpl = self.env.from_string(tpl_str)
        context = {k: v for k, v in data.items()}
        try:
            return tpl.render(**context)
        except Exception as e:
            logger.exception("Template render failed for %s: %s", entity_type, e)
            return f"# {data.get('name', 'Unknown')}\n\n*Template error*"

    def render_changelog(self, entries: list) -> str:
        return self.render("changelog", {"entries": entries})


def _pci_main_devices(devices):
    return [d for d in (devices or []) if d.get("device_name")] if isinstance(devices, list) else []


def _pci_other_devices(devices):
    return [d for d in (devices or []) if isinstance(devices, list) and not d.get("device_name")]


def compute_diff(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> str:
    """Human-readable field diff between the stored and current entity snapshot."""
    if not old:
        return "Updated wiki page"
    old = old or {}
    changes = []

    def add(label, o, n, fmt=str):
        if fmt(o) != fmt(n):
            changes.append(f"{label}: {fmt(o)} → {fmt(n)}")

    add("status", old.get("status"), new.get("status"))
    add("cores", old.get("cores"), new.get("cores"))
    add("RAM", old.get("memory_mb"), new.get("memory_mb"),
        lambda v: f"{v}MB" if v else "-")
    add("IP", old.get("ip_addresses"), new.get("ip_addresses"))
    add("node", old.get("node"), new.get("node"))
    add("disk", old.get("maxdisk"), new.get("maxdisk"), format_size)
    return ", ".join(changes) if changes else "Updated wiki page"


def hash_entity(data: Dict[str, Any]) -> str:
    raw = "|".join(str(data.get(k, "")) for k in [
        "id", "name", "node", "status", "type", "ip",
        "cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk",
        "uptime", "tags",
    ])
    return hashlib.sha256(raw.encode()).hexdigest()
