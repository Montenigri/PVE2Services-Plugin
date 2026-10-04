"""PVE2Proxy — Pydantic models for config, mappings, and sync results."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

_URL_SCHEMES = ("http://", "https://", "ssh://", "sftp://", "tcp://")


def strip_url_noise(value: str) -> str:
    """Normalise user-entered host/domain/path values.

    Drops a leading URL scheme (``http://``, ``ssh://``…) and any trailing
    slashes so values like ``http://192.168.1.5/`` or ``/etc/nginx/conf.d/`` do
    not carry that noise into the stored config or the generated proxy config.
    """
    value = (value or "").strip()
    lowered = value.lower()
    for scheme in _URL_SCHEMES:
        if lowered.startswith(scheme):
            value = value[len(scheme):]
            break
    return value.rstrip("/")


class ProxyConfig(BaseModel):
    enabled: bool = False
    proxy_type: str = "nginx"
    base_domain: str = ""
    default_port: int = 80
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_key: str = ""
    nginx_output_path: str = "/etc/nginx/conf.d/pve2proxy.conf"
    traefik_output_dir: str = "/etc/traefik/dynamic"
    nginx_reload_cmd: str = "nginx -s reload"
    auto_sync: bool = False
    sync_interval_minutes: int = 60

    @field_validator("base_domain", "ssh_host", "nginx_output_path", "traefik_output_dir")
    @classmethod
    def _clean_url_fields(cls, v: str) -> str:
        return strip_url_noise(v)

    @field_validator("nginx_reload_cmd")
    @classmethod
    def validate_reload_cmd(cls, v: str) -> str:
        allowed = ["nginx", "systemctl", "service", "supervisorctl",
                    "/usr/sbin/nginx", "/bin/systemctl", "/usr/bin/systemctl"]
        if v:
            cmd = v.strip().split()[0] if v.strip() else ""
            if cmd and not any(cmd == a or cmd.startswith(a + " ") or cmd.startswith(a + "\t") for a in allowed):
                raise ValueError(f"Reload command '{cmd}' is not allowed. Must be one of: {', '.join(allowed)}")
        return v


class ProxyMappingIn(BaseModel):
    machine_id: str
    machine_name: str = ""
    hostname: str = ""
    domain: str = ""
    ip_address: str = ""
    port: int = 80
    websocket: bool = False
    cache: bool = False
    rate_limit: int = 0
    ssl_enabled: bool = False
    extra_directives: str = ""
    enabled: bool = True

    @field_validator("extra_directives")
    @classmethod
    def sanitise_directives(cls, v: str) -> str:
        if not v:
            return v
        blocked = [
            "include ", "worker_processes", "pid ", "server{", "server {",
            "events{", "events {", "http{", "http {", "error_log ",
            "access_log ", "daemon ", "user ", "location{", "location {",
            "proxy_pass", "upstream{", "upstream {", "resolver ",
        ]
        lower = v.lower().replace(" ", "").replace("\t", "")
        for b in blocked:
            if b.lower().replace(" ", "").replace("\t", "") in lower:
                raise ValueError(f"Directive starting with '{b}' is not allowed")
        return v


class ProxyMappingOut(BaseModel):
    id: int
    machine_id: str
    machine_name: str = ""
    hostname: str = ""
    domain: str = ""
    ip_address: str = ""
    port: int = 80
    websocket: bool = False
    cache: bool = False
    rate_limit: int = 0
    ssl_enabled: bool = False
    extra_directives: str = ""
    enabled: bool = True
    last_deployed: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DeployResult(BaseModel):
    status: str
    message: str = ""
    config: str = ""
    provider: str = ""
