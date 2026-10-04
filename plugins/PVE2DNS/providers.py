"""DNS provider interface and implementations.

Extend by subclassing DNSProvider and adding a factory entry in _create_providers.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote, urljoin

import httpx

logger = logging.getLogger("pve2dns.providers")


class DNSProvider(ABC):
    @abstractmethod
    async def test_connection(self) -> dict:
        ...

    @abstractmethod
    async def create_record(self, hostname: str, ip: str) -> bool:
        ...

    @abstractmethod
    async def delete_record(self, hostname: str, ip: str) -> bool:
        ...

    async def close(self) -> None:
        """Release provider resources (e.g. log out a session). No-op by default."""
        return None

    async def bulk_sync(self, records: List[Dict[str, str]]) -> dict:
        success = 0
        errors: List[str] = []

        async def _create_one(r: Dict[str, str]) -> None:
            nonlocal success
            try:
                ok = await self.create_record(r["hostname"], r["ip"])
                if ok:
                    success += 1
                else:
                    errors.append(f"Failed to create {r['hostname']} -> {r['ip']}")
            except Exception as e:
                errors.append(f"{r.get('hostname','?')}: {e}")

        semaphore = asyncio.Semaphore(5)

        async def _limited(r: Dict[str, str]) -> None:
            async with semaphore:
                await _create_one(r)

        await asyncio.gather(*[_limited(r) for r in records])
        return {"success": success, "errors": errors}


class PiHoleProvider(DNSProvider):
    """Pi-hole provider supporting both API generations.

    ``api_version`` selects the backend:

    * ``v5`` (legacy) — ``/admin/api.php`` with the web password **hash** as
      the ``auth`` parameter. Local DNS records are not manageable through this
      API (Pi-hole v5 has no REST endpoint for ``custom.list``).
    * ``v6`` (current) — the REST API: ``POST /api/auth`` returns a session id
      (sent as ``X-FTL-SID``) and local DNS records live in
      ``/api/config/dns/hosts`` as ``"<ip> <hostname>"`` entries. ``token`` is
      the Pi-hole **web/API password**.
    """

    def __init__(self, url: str, token: str, api_version: str = "v6"):
        self.base_url = url.rstrip("/")
        self.token = token
        self.api_version = (api_version or "v6").strip().lower()
        self._sid: Optional[str] = None
        self._sid_expiry: Optional[datetime] = None
        self._sid_lock = asyncio.Lock()

    @property
    def _is_v6(self) -> bool:
        return self.api_version in ("v6", "6")

    # ----- Pi-hole v5 (legacy /admin/api.php) -----

    async def _api_v5(self, params: dict) -> Optional[dict]:
        params["auth"] = self.token
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(urljoin(self.base_url, "/admin/api.php"), params=params)
            r.raise_for_status()
            return r.json()

    # ----- Pi-hole v6 (REST API) -----

    async def _v6_headers(self, client: httpx.AsyncClient) -> dict:
        """Return auth headers, reusing a cached session id when still valid."""
        async with self._sid_lock:
            if self._sid and self._sid_expiry and datetime.now() < self._sid_expiry:
                return {"X-FTL-SID": self._sid}
            r = await client.post(
                urljoin(self.base_url, "/api/auth"),
                json={"password": self.token},
            )
            r.raise_for_status()
            session = (r.json() or {}).get("session") or {}
            sid = session.get("sid")
            if not sid:
                raise RuntimeError("Pi-hole v6 authentication failed (check password)")
            validity = int(session.get("validity") or 300)
            self._sid = sid
            self._sid_expiry = datetime.now() + timedelta(seconds=max(validity - 30, 30))
            return {"X-FTL-SID": self._sid}

    async def _v6_hosts(self, client: httpx.AsyncClient, headers: dict) -> List[str]:
        r = await client.get(urljoin(self.base_url, "/api/config/dns/hosts"), headers=headers)
        r.raise_for_status()
        config = (r.json() or {}).get("config") or {}
        return ((config.get("dns") or {}).get("hosts")) or []

    @staticmethod
    def _v6_entry(ip: str, hostname: str) -> str:
        return f"{ip} {hostname}"

    async def _v6_add(self, client: httpx.AsyncClient, headers: dict, entry: str) -> bool:
        if entry in await self._v6_hosts(client, headers):
            return True  # idempotent: already present
        path = f"/api/config/dns/hosts/{quote(entry, safe='')}"
        r = await client.put(urljoin(self.base_url, path), headers=headers)
        if r.status_code in (200, 201, 204):
            return True
        if r.status_code == 400:
            # Pi-hole answers 400 for a duplicate; re-check to treat it as OK.
            return entry in await self._v6_hosts(client, headers)
        return False

    async def _v6_delete(self, client: httpx.AsyncClient, headers: dict, entry: str) -> bool:
        path = f"/api/config/dns/hosts/{quote(entry, safe='')}"
        r = await client.delete(urljoin(self.base_url, path), headers=headers)
        return r.status_code in (200, 204, 404)

    # ----- DNSProvider API -----

    async def test_connection(self) -> dict:
        try:
            if self._is_v6:
                async with httpx.AsyncClient(timeout=10) as c:
                    headers = await self._v6_headers(c)
                    r = await c.get(urljoin(self.base_url, "/api/info/version"), headers=headers)
                    r.raise_for_status()
                    core = (((r.json() or {}).get("version") or {}).get("core") or {}).get("local") or {}
                    return {"connected": True, "api": "v6", "version": core.get("version")}
            data = await self._api_v5({"status": ""})
            status = data.get("status") if isinstance(data, dict) else None
            if status:
                return {"connected": True, "api": "v5", "status": status}
            return {"connected": False, "error": "Unexpected response"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def create_record(self, hostname: str, ip: str) -> bool:
        if self._is_v6:
            async with httpx.AsyncClient(timeout=10) as c:
                headers = await self._v6_headers(c)
                return await self._v6_add(c, headers, self._v6_entry(ip, hostname))
        data = await self._api_v5({"action": "add", "domain": hostname, "ip": ip})
        if data and isinstance(data, dict):
            # Pi-hole v5 replies {"status": "success"}; older wrappers may use "success"
            return data.get("status") == "success" or data.get("success", False) is True
        return False

    async def delete_record(self, hostname: str, ip: str) -> bool:
        if self._is_v6:
            async with httpx.AsyncClient(timeout=10) as c:
                headers = await self._v6_headers(c)
                return await self._v6_delete(c, headers, self._v6_entry(ip, hostname))
        data = await self._api_v5({"action": "delete", "domain": hostname, "ip": ip})
        if data and isinstance(data, dict):
            return data.get("status") == "success" or data.get("success", False) is True
        return False

    async def close(self) -> None:
        """Log out the Pi-hole v6 session so sessions do not pile up.

        Pi-hole caps concurrent API sessions (``webserver.api.max_sessions``,
        default 16); leaking one per test/sync eventually returns
        ``api_seats_exceeded``.
        """
        if not self._is_v6:
            return
        async with self._sid_lock:
            sid, self._sid = self._sid, None
            self._sid_expiry = None
        if not sid:
            return
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.delete(
                    urljoin(self.base_url, "/api/auth"),
                    headers={"X-FTL-SID": sid},
                )
        except Exception:  # noqa: BLE001 — logout is best-effort
            logger.debug("Pi-hole v6 logout failed", exc_info=True)


class AdGuardProvider(DNSProvider):
    """AdGuard Home provider.

    AdGuard accepts the admin credentials via HTTP **Basic auth** on every
    ``/control/*`` endpoint, so there is no login/session dance (the old code
    looked for a ``session`` cookie, but AdGuard sets ``agh_session`` and
    returns a plain ``OK`` body).

    AdGuard also stores **duplicate** rewrites, so creates are made idempotent
    by listing first and skipping an entry that already exists.
    """

    def __init__(self, url: str, username: str, password: str):
        self.base_url = url.rstrip("/")
        self.username = username
        self.password = password

    @property
    def _auth(self) -> tuple:
        return (self.username, self.password)

    async def _list_rewrites(self, client: httpx.AsyncClient) -> List[dict]:
        r = await client.get(
            urljoin(self.base_url, "/control/rewrite/list"),
            auth=self._auth,
        )
        r.raise_for_status()
        return r.json() or []

    @staticmethod
    def _has(rewrites: List[dict], hostname: str, ip: str) -> bool:
        return any(
            r.get("domain") == hostname and str(r.get("answer", "")) == ip
            for r in rewrites
        )

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    urljoin(self.base_url, "/control/status"),
                    auth=self._auth,
                )
                r.raise_for_status()
                data = r.json()
                return {"connected": True, "api": "adguard", "version": data.get("version", "unknown")}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def create_record(self, hostname: str, ip: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as c:
            if self._has(await self._list_rewrites(c), hostname, ip):
                return True  # already present — keep sync idempotent
            r = await c.post(
                urljoin(self.base_url, "/control/rewrite/add"),
                auth=self._auth,
                json={"domain": hostname, "answer": ip},
            )
            return r.status_code == 200

    async def delete_record(self, hostname: str, ip: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as c:
            if not self._has(await self._list_rewrites(c), hostname, ip):
                return True  # nothing to do
            r = await c.post(
                urljoin(self.base_url, "/control/rewrite/delete"),
                auth=self._auth,
                json={"domain": hostname, "answer": ip},
            )
            return r.status_code == 200


def create_providers(config: dict) -> List[DNSProvider]:
    providers: List[DNSProvider] = []
    if config.get("pihole_enabled") and config.get("pihole_url") and config.get("pihole_token"):
        providers.append(PiHoleProvider(
            url=config["pihole_url"],
            token=config["pihole_token"],
            api_version=config.get("pihole_api_version", "v6"),
        ))
    if config.get("adguard_enabled") and config.get("adguard_url") and config.get("adguard_username"):
        providers.append(AdGuardProvider(
            url=config["adguard_url"],
            username=config["adguard_username"],
            password=config.get("adguard_password", ""),
        ))
    return providers
