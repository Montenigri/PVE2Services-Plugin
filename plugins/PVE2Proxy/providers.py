"""Proxy config generators — Nginx and Traefik.

Extend by subclassing ProxyProvider and adding a factory entry.
"""

import logging
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger("pve2proxy.providers")


class ProxyProvider(ABC):
    @abstractmethod
    def generate(self, mappings: List[dict], config: dict) -> str:
        ...

    @abstractmethod
    def get_output_path(self, config: dict) -> str:
        ...

    def get_reload_command(self, config: dict) -> str:
        return ""

    def validate_mapping(self, m: dict) -> str:
        parts = []
        if m.get("hostname"):
            parts.append(m["hostname"])
        if m.get("domain"):
            parts.append(m["domain"])
        domain = ".".join(parts)
        if not domain:
            return ""
        return domain


class NginxProvider(ProxyProvider):
    CACHE_ZONE = "my_cache"
    RATE_ZONE = "pve2proxy"

    def generate(self, mappings: List[dict], config: dict) -> str:
        enabled = [
            m for m in mappings
            if m.get("enabled", True) and self.validate_mapping(m)
        ]
        blocks = []
        for m in enabled:
            domain = self.validate_mapping(m)
            ip = m.get("ip_address", "")
            port = m.get("port", config.get("default_port", 80))
            blocks.append(self._server_block(domain, ip, port, m))
        lines = [
            "# PVE2Proxy — auto-generated nginx config",
            "# Do not edit manually — changes will be overwritten on next deploy",
            "",
        ]
        lines.extend(self._prelude(enabled))
        lines.extend(blocks)
        lines.append("")
        return "\n".join(lines)

    def _prelude(self, mappings: List[dict]) -> List[str]:
        """Define the http-context zones the generated blocks reference.

        Without these, nginx refuses to load a config that uses ``cache`` or
        ``rate_limit`` ("zone is unknown"). ``conf.d/*.conf`` is included inside
        ``http {}`` on standard nginx installs, so the directives are valid here.
        """
        lines: List[str] = []
        if any(m.get("cache") for m in mappings):
            lines.append(
                f"proxy_cache_path /var/cache/nginx levels=1:2 "
                f"keys_zone={self.CACHE_ZONE}:10m max_size=1g inactive=60m "
                f"use_temp_path=off;"
            )
        rates = [int(m.get("rate_limit", 0)) for m in mappings if int(m.get("rate_limit", 0)) > 0]
        if rates:
            lines.append(
                f"limit_req_zone $binary_remote_addr zone={self.RATE_ZONE}:10m "
                f"rate={max(rates)}r/s;"
            )
        if lines:
            lines.append("")
        return lines

    def _server_block(self, domain: str, ip: str, port: int, m: dict) -> str:
        upstream = f"http://{ip}:{port}" if port != 443 else f"https://{ip}:{port}"
        listen = ["443 ssl"] if m.get("ssl_enabled") else ["80"]
        lines = ["server {", f"  server_name {domain};"]

        for lsn in listen:
            lines.append(f"  listen {lsn};")

        if m.get("ssl_enabled"):
            lines.append(f"  ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;")
            lines.append(f"  ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;")
            lines.append("  ssl_protocols TLSv1.2 TLSv1.3;")
            lines.append("  ssl_ciphers HIGH:!aNULL:!MD5;")

        if m.get("websocket"):
            lines.append("")
            lines.append("  # WebSocket support")
            lines.append('  proxy_set_header Upgrade $http_upgrade;')
            lines.append('  proxy_set_header Connection "upgrade";')

        if m.get("cache"):
            lines.append("")
            lines.append("  # Cache")
            lines.append(f"  proxy_cache {self.CACHE_ZONE};")
            lines.append("  proxy_cache_valid 200 302 10m;")
            lines.append("  proxy_cache_valid 404 1m;")
            lines.append("  proxy_cache_use_stale error timeout updating;")

        rl = m.get("rate_limit", 0)
        if rl > 0:
            lines.append("")
            lines.append("  # Rate limiting")
            lines.append(f"  limit_req zone={self.RATE_ZONE} burst={rl * 2} nodelay;")

        extra = m.get("extra_directives", "").strip()
        if extra:
            lines.append("")
            lines.append("  # Custom directives")
            for line in extra.split("\n"):
                stripped = line.strip()
                if stripped:
                    lines.append(f"  {stripped}")

        lines.append("")
        lines.append("  location / {")
        lines.append(f"    proxy_pass {upstream};")
        lines.append('    proxy_set_header Host $host;')
        lines.append('    proxy_set_header X-Real-IP $remote_addr;')
        lines.append('    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;')
        lines.append('    proxy_set_header X-Forwarded-Proto $scheme;')
        lines.append("  }")
        lines.append("}")
        return "\n".join(lines)

    def get_output_path(self, config: dict) -> str:
        return config.get("nginx_output_path", "/etc/nginx/conf.d/pve2proxy.conf")

    def get_reload_command(self, config: dict) -> str:
        return config.get("nginx_reload_cmd", "nginx -s reload")


class TraefikProvider(ProxyProvider):
    def generate(self, mappings: List[dict], config: dict) -> str:
        routers = []
        services = []
        middlewares = {}
        for m in mappings:
            if not m.get("enabled", True):
                continue
            domain = self.validate_mapping(m)
            if not domain:
                continue
            ip = m.get("ip_address", "")
            port = m.get("port", config.get("default_port", 80))
            sid = domain.replace(".", "-")
            url = f"http://{ip}:{port}" if port != 443 else f"https://{ip}:{port}"

            router_entry = f'    {sid}-router:'
            router_entry += f'\n      rule: "Host(`{domain}`)"'
            router_entry += f'\n      service: {sid}-service'
            if m.get("ssl_enabled"):
                router_entry += '\n      tls:'
                router_entry += '\n        certResolver: letsencrypt'

            mids = []
            if m.get("rate_limit", 0) > 0:
                mid_name = f"{sid}-ratelimit"
                mids.append(mid_name)
                if mid_name not in middlewares:
                    middlewares[mid_name] = {
                        "rateLimit": {"average": m["rate_limit"], "burst": m["rate_limit"] * 2}
                    }
            # NOTE: Traefik has no built-in response-cache middleware, so
            # ``cache`` is intentionally a no-op here (nginx-only feature).

            if mids:
                router_entry += '\n      middlewares:'
                for mid in mids:
                    router_entry += f'\n        - {mid}'

            routers.append(router_entry)

            services.append(
                f'    {sid}-service:'
                f'\n      loadBalancer:'
                f'\n        servers:'
                f'\n          - url: "{url}"'
            )

        lines = [
            "# PVE2Proxy — auto-generated Traefik dynamic config",
            "# Do not edit manually — changes are overwritten on deploy",
            "http:",
            "  routers:",
        ]
        lines.extend(routers)
        lines.append("")
        lines.append("  services:")
        lines.extend(services)

        if middlewares:
            lines.append("")
            lines.append("  middlewares:")
            for name, cfg in middlewares.items():
                lines.append(f"    {name}:")
                for key, val in cfg.items():
                    lines.append(f"      {key}:")
                    for k, v in val.items():
                        lines.append(f"        {k}: {v}")

        lines.append("")
        return "\n".join(lines)

    def get_output_path(self, config: dict) -> str:
        # Traefik's file provider watches a *directory* and only loads files
        # with a recognised extension, so write one named file into it (writing
        # to the bare directory produced an extension-less, ignored file).
        directory = config.get("traefik_output_dir", "/etc/traefik/dynamic").rstrip("/")
        return f"{directory}/pve2proxy.yml"

    def get_reload_command(self, config: dict) -> str:
        return ""


def create_providers(config: dict) -> ProxyProvider:
    ptype = config.get("proxy_type", "nginx")
    if ptype == "traefik":
        return TraefikProvider()
    return NginxProvider()
