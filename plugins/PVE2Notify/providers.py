"""Notification provider interface and implementations.

Extend by subclassing NotifyProvider and adding a factory entry in create_providers.
"""

import logging
from abc import ABC, abstractmethod
from typing import List

import httpx

logger = logging.getLogger("pve2notify.providers")

EVENT_COLORS = {
    "started": 0x10B981,
    "stopped": 0xDC2626,
    "added": 0x3B82F6,
    "removed": 0xF59E0B,
}

EVENT_ICONS = {
    "started": ":green_circle:",
    "stopped": ":red_circle:",
    "added": ":large_blue_circle:",
    "removed": ":orange_circle:",
}

EVENT_LABELS = {
    "started": "Machine Started",
    "stopped": "Machine Stopped",
    "added": "Machine Added",
    "removed": "Machine Removed",
}

# Colors/icons for cross-plugin generic notifications (see bridge.py).
GENERIC_EVENT_COLORS = {
    "on_battery": 0xF59E0B,
    "low_battery": 0xDC2626,
    "ups_online": 0x10B981,
    "comm_lost": 0xDC2626,
    "comm_restored": 0x10B981,
    "custom": 0x6B7280,
}

GENERIC_EVENT_ICONS = {
    "on_battery": ":zap:",
    "low_battery": ":red_circle:",
    "ups_online": ":green_circle:",
    "comm_lost": ":no_entry_sign:",
    "comm_restored": ":white_check_mark:",
    "custom": ":bell:",
}


class NotifyProvider(ABC):
    @abstractmethod
    async def send_event(self, event_type: str, machine: dict) -> bool:
        ...

    @abstractmethod
    async def send_test(self) -> dict:
        ...

    @abstractmethod
    async def send_generic(self, title: str, description: str,
                           fields: List[dict], event_type: str, source: str) -> bool:
        """Send a generic notification (used by the bridge for other plugins)."""
        ...


def _machine_summary(m: dict) -> str:
    name = m.get("machine_name") or m.get("name") or f"#{m.get('machine_id','?')}"
    mid = m.get("machine_id", "?")
    node = m.get("node", "?")
    mtype = m.get("machine_type") or m.get("type", "vm")
    return f"{name} (#{mid}) on {node} ({mtype.upper()})"


class DiscordProvider(NotifyProvider):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def _post(self, payload: dict) -> bool:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(self.webhook_url, json=payload)
            return r.is_success

    async def send_event(self, event_type: str, machine: dict) -> bool:
        color = EVENT_COLORS.get(event_type, 0x6B7280)
        label = EVENT_LABELS.get(event_type, event_type)
        summary = _machine_summary(machine)
        embed = {
            "title": label,
            "description": summary,
            "color": color,
            "fields": [
                {"name": "Machine", "value": machine.get("machine_name") or machine.get("name") or "?", "inline": True},
                {"name": "ID", "value": machine.get("machine_id", "?"), "inline": True},
                {"name": "Type", "value": machine.get("machine_type") or machine.get("type", "vm"), "inline": True},
                {"name": "Node", "value": machine.get("node", "?"), "inline": True},
                {"name": "Status", "value": machine.get("status", "?"), "inline": True},
            ],
            "footer": {"text": "PVE2Notify"},
        }
        if event_type in ("started", "stopped"):
            prev = machine.get("previous_status", "?")
            embed["fields"].append({"name": "Previous", "value": prev, "inline": True})
        return await self._post({"embeds": [embed]})

    async def send_generic(self, title: str, description: str,
                           fields: List[dict], event_type: str, source: str) -> bool:
        embed = {
            "title": title,
            "description": description,
            "color": GENERIC_EVENT_COLORS.get(event_type, GENERIC_EVENT_COLORS["custom"]),
            "fields": [{"name": f.get("name", ""), "value": str(f.get("value", "")), "inline": True}
                       for f in (fields or [])],
            "footer": {"text": source},
        }
        return await self._post({"embeds": [embed]})

    async def send_test(self) -> dict:
        ok = await self._post({
            "embeds": [{
                "title": "PVE2Notify Test",
                "description": "Notification system is working.",
                "color": 0x10B981,
                "footer": {"text": "PVE2Notify"},
            }]
        })
        return {"success": ok, "error": "" if ok else "Webhook rejected"}


class SlackProvider(NotifyProvider):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def _post(self, payload: dict) -> bool:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(self.webhook_url, json=payload)
            return r.is_success

    async def send_event(self, event_type: str, machine: dict) -> bool:
        label = EVENT_LABELS.get(event_type, event_type)
        summary = _machine_summary(machine)
        emoji = {"started": ":large_green_circle:", "stopped": ":red_circle:", "added": ":large_blue_circle:", "removed": ":orange_circle:"}.get(event_type, ":bell:")
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} {label}"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Machine:*\n{machine.get('machine_name') or machine.get('name') or '?'}"},
                {"type": "mrkdwn", "text": f"*ID:*\n{machine.get('machine_id','?')}"},
            ]},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Type:*\n{machine.get('machine_type') or machine.get('type','vm')}"},
                {"type": "mrkdwn", "text": f"*Node:*\n{machine.get('node','?')}"},
            ]},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Status:*\n{machine.get('status','?')}"},
                {"type": "mrkdwn", "text": f"*Previous:*\n{machine.get('previous_status','?')}" if event_type in ("started","stopped") else f"*Time:*\n{EVENT_LABELS.get(event_type,event_type)}"},
            ]},
        ]
        return await self._post({"text": summary, "blocks": blocks})

    async def send_generic(self, title: str, description: str,
                           fields: List[dict], event_type: str, source: str) -> bool:
        emoji = GENERIC_EVENT_ICONS.get(event_type, GENERIC_EVENT_ICONS["custom"])
        blocks: List[dict] = [
            {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} {title}"}},
        ]
        if description:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": description}})
        if fields:
            blocks.append({"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*{f.get('name', '')}:*\n{f.get('value', '')}"}
                for f in fields
            ]})
        return await self._post({"text": title, "blocks": blocks})

    async def send_test(self) -> dict:
        ok = await self._post({
            "text": "PVE2Notify test — notification system is working.",
        })
        return {"success": ok, "error": "" if ok else "Webhook rejected"}


class MattermostProvider(NotifyProvider):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def _post(self, payload: dict) -> bool:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(self.webhook_url, json=payload)
            return r.is_success

    async def send_event(self, event_type: str, machine: dict) -> bool:
        label = EVENT_LABELS.get(event_type, event_type)
        summary = _machine_summary(machine)
        icon = EVENT_ICONS.get(event_type, ":bell:")
        name = machine.get("machine_name") or machine.get("name") or "?"
        mid = machine.get("machine_id", "?")
        mtype = machine.get("machine_type") or machine.get("type", "vm")
        node = machine.get("node", "?")
        status = machine.get("status", "?")
        prev = machine.get("previous_status", "?")
        text = f"{icon} **{label}**\n> {summary}\n\n| | |\n|---|---|\n| Machine | {name} |\n| ID | {mid} |\n| Type | {mtype.upper()} |\n| Node | {node} |\n| Status | {status} |"
        if event_type in ("started", "stopped"):
            text += f"\n| Previous | {prev} |"
        return await self._post({"text": text})

    async def send_generic(self, title: str, description: str,
                           fields: List[dict], event_type: str, source: str) -> bool:
        icon = GENERIC_EVENT_ICONS.get(event_type, GENERIC_EVENT_ICONS["custom"])
        text = f"{icon} **{title}**"
        if description:
            text += f"\n> {description}"
        if fields:
            text += "\n\n| | |\n|---|---|"
            for f in fields:
                text += f"\n| {f.get('name', '')} | {f.get('value', '')} |"
        return await self._post({"text": text})

    async def send_test(self) -> dict:
        ok = await self._post({"text": ":white_check_mark: **PVE2Notify test** — notification system is working."})
        return {"success": ok, "error": "" if ok else "Webhook rejected"}


class TelegramProvider(NotifyProvider):
    def __init__(self, bot_token: str, chat_id: str):
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self.chat_id = chat_id

    async def _send_message(self, text: str, parse_mode: str = "HTML") -> tuple[bool, str]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{self.api_url}/sendMessage", json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            })
            if r.is_success:
                return True, ""
            try:
                desc = r.json().get("description", r.text)
            except Exception:
                desc = r.text
            return False, desc

    async def send_event(self, event_type: str, machine: dict) -> bool:
        label = EVENT_LABELS.get(event_type, event_type)
        name = machine.get("machine_name") or machine.get("name") or "?"
        mid = machine.get("machine_id", "?")
        mtype = machine.get("machine_type") or machine.get("type", "vm")
        node = machine.get("node", "?")
        status = machine.get("status", "?")
        prev = machine.get("previous_status", "?")
        text = (
            f"<b>{label}</b>\n"
            f"<b>Machine:</b> {name}\n"
            f"<b>ID:</b> {mid}\n"
            f"<b>Type:</b> {mtype.upper()}\n"
            f"<b>Node:</b> {node}\n"
            f"<b>Status:</b> {status}"
        )
        if event_type in ("started", "stopped"):
            text += f"\n<b>Previous:</b> {prev}"
        ok, _ = await self._send_message(text)
        return ok

    async def send_generic(self, title: str, description: str,
                           fields: List[dict], event_type: str, source: str) -> bool:
        text = f"<b>{title}</b>"
        if description:
            text += f"\n{description}"
        for f in (fields or []):
            text += f"\n<b>{f.get('name', '')}:</b> {f.get('value', '')}"
        ok, _ = await self._send_message(text)
        return ok

    async def send_test(self) -> dict:
        ok, err_msg = await self._send_message(
            "<b>PVE2Notify test</b> — notification system is working."
        )
        return {"success": ok, "error": err_msg}


def create_providers(config: dict) -> List[NotifyProvider]:
    providers: List[NotifyProvider] = []
    if config.get("discord_enabled") and config.get("discord_webhook_url"):
        providers.append(DiscordProvider(config["discord_webhook_url"]))
    if config.get("slack_enabled") and config.get("slack_webhook_url"):
        providers.append(SlackProvider(config["slack_webhook_url"]))
    if config.get("mattermost_enabled") and config.get("mattermost_webhook_url"):
        providers.append(MattermostProvider(config["mattermost_webhook_url"]))
    if config.get("telegram_enabled") and config.get("telegram_bot_token") and config.get("telegram_chat_id"):
        providers.append(TelegramProvider(config["telegram_bot_token"], config["telegram_chat_id"]))
    return providers
