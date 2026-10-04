"""Tests for PVE2Proxy plugin — proxy mapping management."""

import asyncio
import os

import pydantic
import pytest
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.plugins.PVE2Proxy import deployer
from PVE2Services.plugins.PVE2Proxy.providers import NginxProvider, TraefikProvider
from PVE2Services.plugins.PVE2Proxy.schemas import ProxyConfig, ProxyMappingIn


class TestPVE2Proxy:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db_path = str(tmp_path / "test_proxy.db")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{self.db_path}"
        self.db = DBAdapter(db_url=f"sqlite:///{self.db_path}")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_mapping_lifecycle(self):
        # Create
        assert self.db.save_proxy_mapping(
            "vm/100", "Web Server", "web", "example.com", "10.0.0.1",
            port=443, ssl_enabled=True, websocket=True
        ) is True
        
        # Read
        mapping = self.db.get_proxy_mapping("vm/100")
        assert mapping is not None
        assert mapping["domain"] == "example.com"
        assert mapping["port"] == 443
        assert mapping["ssl_enabled"]  # SQLite returns 1, which is truthy
        assert mapping["websocket"]  # SQLite returns 1, which is truthy
        
        # Update
        self.db.save_proxy_mapping("vm/100", "Web Server v2", "web2", "example2.com", "10.0.0.2")
        mapping = self.db.get_proxy_mapping("vm/100")
        assert mapping["domain"] == "example2.com"
        
        # Delete
        assert self.db.delete_proxy_mapping("vm/100") is True
        assert self.db.get_proxy_mapping("vm/100") is None

    def test_mark_deployed(self):
        self.db.save_proxy_mapping("vm/100", "Test VM")
        self.db.save_proxy_mapping("vm/200", "Test VM 2")
        self.db.mark_proxy_deployed(["vm/100"])
        
        mapping1 = self.db.get_proxy_mapping("vm/100")
        mapping2 = self.db.get_proxy_mapping("vm/200")
        assert mapping1["last_deployed"] is not None
        assert mapping2["last_deployed"] is None

    def test_extra_directives(self):
        self.db.save_proxy_mapping(
            "vm/100", "Test VM", "test", "example.com", "10.0.0.1",
            extra_directives="proxy_set_header X-Custom true;"
        )
        mapping = self.db.get_proxy_mapping("vm/100")
        assert "proxy_set_header" in mapping["extra_directives"]

    def test_rate_limit(self):
        self.db.save_proxy_mapping(
            "vm/100", "Test VM", "test", "example.com", "10.0.0.1",
            rate_limit=100
        )
        mapping = self.db.get_proxy_mapping("vm/100")
        assert mapping["rate_limit"] == 100


def _m(**kw):
    m = {"hostname": "app", "domain": "lab.local", "ip_address": "10.0.0.5",
         "port": 8080, "enabled": True}
    m.update(kw)
    return m


class TestNginxProvider:
    def test_server_block(self):
        out = NginxProvider().generate([_m(websocket=True)], {"default_port": 80})
        assert "server_name app.lab.local;" in out
        assert "listen 80;" in out
        assert "proxy_pass http://10.0.0.5:8080;" in out
        assert "Upgrade $http_upgrade" in out

    def test_disabled_and_empty_skipped(self):
        out = NginxProvider().generate(
            [_m(enabled=False), {"hostname": "", "domain": "", "enabled": True}], {}
        )
        assert "server {" not in out

    def test_cache_and_ratelimit_define_zones(self):
        """The generated blocks reference zones; the config must define them."""
        out = NginxProvider().generate([_m(cache=True, rate_limit=5)], {})
        assert "proxy_cache_path" in out and "keys_zone=my_cache" in out
        assert "proxy_cache my_cache;" in out
        assert "limit_req_zone" in out and "rate=5r/s" in out
        assert "limit_req zone=pve2proxy burst=10 nodelay;" in out

    def test_no_zone_prelude_without_features(self):
        out = NginxProvider().generate([_m()], {})
        assert "proxy_cache_path" not in out
        assert "limit_req_zone" not in out


class TestTraefikProvider:
    def test_generate(self):
        out = TraefikProvider().generate(
            [_m(rate_limit=3)], {}
        )
        assert "Host(`app.lab.local`)" in out
        assert "app-lab-local-service" in out
        assert "rateLimit" in out

    def test_yaml_structure_is_nested_correctly(self):
        """The dynamic file must nest routers/services under http: (Traefik
        rejects sibling keys with 'field not found')."""
        import yaml

        out = TraefikProvider().generate([_m(rate_limit=3, cache=True)], {})
        data = yaml.safe_load(out)
        router = data["http"]["routers"]["app-lab-local-router"]
        assert router["rule"] == "Host(`app.lab.local`)"
        assert router["service"] == "app-lab-local-service"
        # rate_limit maps to Traefik's RateLimit middleware; cache is nginx-only
        assert router["middlewares"] == ["app-lab-local-ratelimit"]
        svc = data["http"]["services"]["app-lab-local-service"]
        assert svc["loadBalancer"]["servers"] == [{"url": "http://10.0.0.5:8080"}]
        assert data["http"]["middlewares"]["app-lab-local-ratelimit"] == {
            "rateLimit": {"average": 3, "burst": 6}
        }
        assert "app-lab-local-cache" not in data["http"].get("middlewares", {})

    def test_output_path_is_a_yaml_file(self):
        p = TraefikProvider()
        assert (
            p.get_output_path({"traefik_output_dir": "/etc/traefik/dynamic/"})
            == "/etc/traefik/dynamic/pve2proxy.yml"
        )
        assert p.get_output_path({"traefik_output_dir": "/x/y"}) == "/x/y/pve2proxy.yml"


class TestDeployer:
    def test_scp_uses_uppercase_port_flag(self):
        args = deployer._ssh_base_args(2222, "/tmp/key", scp=True)
        assert args[args.index("-P") + 1] == "2222"

    def test_ssh_uses_lowercase_port_flag(self):
        args = deployer._ssh_base_args(22, "/tmp/key", scp=False)
        assert args[args.index("-p") + 1] == "22"

    def test_deploy_without_host_fails_fast(self):
        result = asyncio.run(deployer.deploy_config("nginx", {}, []))
        assert result["status"] == "error"
        assert "host" in result["message"].lower()


class TestSchemas:
    def test_reload_command_allowlist(self):
        ProxyConfig(nginx_reload_cmd="nginx -s reload")  # allowed
        with pytest.raises(pydantic.ValidationError):
            ProxyConfig(nginx_reload_cmd="rm -rf /")

    def test_extra_directives_cannot_inject_proxy_pass(self):
        with pytest.raises(pydantic.ValidationError):
            ProxyMappingIn(machine_id="1", extra_directives="proxy_pass http://evil;")
        ProxyMappingIn(machine_id="1", extra_directives="proxy_set_header X-Y true;")

    def test_url_and_trailing_slash_noise_is_stripped(self):
        cfg = ProxyConfig(
            base_domain="http://lab.local/",
            ssh_host="192.168.1.5/",
            nginx_output_path="/etc/nginx/conf.d/pve2proxy.conf/",
            traefik_output_dir="/etc/traefik/dynamic/",
        )
        assert cfg.base_domain == "lab.local"
        assert cfg.ssh_host == "192.168.1.5"
        assert cfg.nginx_output_path == "/etc/nginx/conf.d/pve2proxy.conf"
        assert cfg.traefik_output_dir == "/etc/traefik/dynamic"

    def test_scheme_prefix_is_stripped(self):
        assert ProxyConfig(ssh_host="ssh://root@host").ssh_host == "root@host"
        assert ProxyConfig(base_domain="https://lab.local/").base_domain == "lab.local"
