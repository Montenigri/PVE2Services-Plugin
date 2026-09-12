"""DNS provider interface and implementations.

Extend by subclassing DNSProvider and adding a factory entry in _create_providers.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin

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
    def __init__(self, url: str, token: str, api_version: str = "v5"):
        self.base_url = url.rstrip("/")
        self.token = token
        self.api_version = api_version

    async def _api(self, params: dict) -> Optional[dict]:
        params["auth"] = self.token
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(urljoin(self.base_url, "/admin/api.php"), params=params)
            r.raise_for_status()
            return r.json()

    async def test_connection(self) -> dict:
        try:
            data = await self._api({})
            if data and isinstance(data, dict) and "status" in data:
                return {"connected": True, "status": data.get("status")}
            return {"connected": False, "error": "Unexpected response"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def create_record(self, hostname: str, ip: str) -> bool:
        data = await self._api({"action": "add", "domain": hostname, "ip": ip})
        if data and isinstance(data, dict):
            # Pi-hole v5 replies {"status": "success"}; older wrappers may use "success"
            return data.get("status") == "success" or data.get("success", False) is True
        return False

    async def delete_record(self, hostname: str, ip: str) -> bool:
        data = await self._api({"action": "delete", "domain": hostname, "ip": ip})
        if data and isinstance(data, dict):
            return data.get("status") == "success" or data.get("success", False) is True
        return False


class AdGuardProvider(DNSProvider):
    def __init__(self, url: str, username: str, password: str):
        self.base_url = url.rstrip("/")
        self.username = username
        self.password = password
        self._session_token: Optional[str] = None
        self._session_expiry: Optional[datetime] = None

    async def _headers(self) -> dict:
        if self._session_token and self._session_expiry and datetime.now() < self._session_expiry:
            return {"Authorization": f"Bearer {self._session_token}", "Content-Type": "application/json"}
        auth = httpx.BasicAuth(self.username, self.password)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                urljoin(self.base_url, "/control/login"),
                json={"name": self.username, "password": self.password},
                auth=auth,
            )
            r.raise_for_status()
            cookie = r.cookies.get("session")
            if cookie:
                self._session_token = cookie
                self._session_expiry = datetime.now() + timedelta(minutes=10)
                return {"Cookie": f"session={cookie}", "Content-Type": "application/json"}
            data = r.json()
            token = data.get("token", "")
            self._session_token = token
            self._session_expiry = datetime.now() + timedelta(minutes=10)
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def test_connection(self) -> dict:
        try:
            headers = await self._headers()
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    urljoin(self.base_url, "/control/status"),
                    headers=headers,
                )
                r.raise_for_status()
                data = r.json()
                return {"connected": True, "version": data.get("version", "unknown")}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def create_record(self, hostname: str, ip: str) -> bool:
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                urljoin(self.base_url, "/control/rewrite/add"),
                headers=headers,
                json={"domain": hostname, "answer": ip},
            )
            return r.status_code == 200

    async def delete_record(self, hostname: str, ip: str) -> bool:
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                urljoin(self.base_url, "/control/rewrite/delete"),
                headers=headers,
                json={"domain": hostname, "answer": ip},
            )
            return r.status_code == 200


def create_providers(config: dict) -> List[DNSProvider]:
    providers: List[DNSProvider] = []
    if config.get("pihole_enabled") and config.get("pihole_url") and config.get("pihole_token"):
        providers.append(PiHoleProvider(
            url=config["pihole_url"],
            token=config["pihole_token"],
            api_version=config.get("pihole_api_version", "v5"),
        ))
    if config.get("adguard_enabled") and config.get("adguard_url") and config.get("adguard_username"):
        providers.append(AdGuardProvider(
            url=config["adguard_url"],
            username=config["adguard_username"],
            password=config.get("adguard_password", ""),
        ))
    return providers
