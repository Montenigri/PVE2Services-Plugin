"""Tests for PVE2Notify plugin — event filtering + Telegram error reporting."""

import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PVE2Services.plugins.PVE2Notify.providers import TelegramProvider
from PVE2Services.plugins.PVE2Notify.schemas import NotifyConfig
from PVE2Services.plugins.PVE2Notify.watcher import diff_snapshots

# ── Telegram error propagation ──────────────────────────────────────────────


class TestTelegramErrorReporting:
    def _provider(self):
        return TelegramProvider("fake-token:xxx", "-100123")

    def _mock_httpx(self, is_success: bool, body: dict | None = None):
        fake_resp = AsyncMock()
        fake_resp.is_success = is_success
        fake_resp.json.return_value = body or {}
        fake_resp.text = json.dumps(body) if body else ""
        ctx = AsyncMock()
        ctx.post.return_value = fake_resp
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    def test_send_test_returns_telegram_error(self):
        ctx = self._mock_httpx(
            False,
            {"error_code": 400, "description": "Bad Request: chat not found"},
        )
        with patch("PVE2Services.plugins.PVE2Notify.providers.httpx.AsyncClient", return_value=ctx):
            result = asyncio.run(self._provider().send_test())

        assert result["success"] is False
        assert "chat not found" in result["error"]

    def test_send_test_returns_empty_on_success(self):
        ctx = self._mock_httpx(True)
        with patch("PVE2Services.plugins.PVE2Notify.providers.httpx.AsyncClient", return_value=ctx):
            result = asyncio.run(self._provider().send_test())

        assert result["success"] is True
        assert result["error"] == ""

    def test_send_event_returns_bool(self):
        ctx = self._mock_httpx(True)
        with patch("PVE2Services.plugins.PVE2Notify.providers.httpx.AsyncClient", return_value=ctx):
            result = asyncio.run(
                self._provider().send_event("started", {"machine_name": "VM1"})
            )
        assert result is True

    def test_send_event_error_blocked_by_user(self):
        ctx = self._mock_httpx(
            False,
            {"error_code": 403, "description": "Forbidden: bot was blocked by the user"},
        )
        with patch("PVE2Services.plugins.PVE2Notify.providers.httpx.AsyncClient", return_value=ctx):
            result = asyncio.run(
                self._provider().send_event("started", {"machine_name": "VM1"})
            )
        assert result is False


# ── NotifyConfig schema defaults ────────────────────────────────────────────


class TestNotifyConfigSchema:
    def test_defaults_have_all_notify_flags_true(self):
        cfg = NotifyConfig()
        assert cfg.notify_started is True
        assert cfg.notify_stopped is True
        assert cfg.notify_added is True
        assert cfg.notify_removed is True

    def test_configurable_flags(self):
        cfg = NotifyConfig(notify_started=False, notify_removed=False)
        assert cfg.notify_started is False
        assert cfg.notify_stopped is True
        assert cfg.notify_added is True
        assert cfg.notify_removed is False


# ── Event filtering via watcher ─────────────────────────────────────────────


class TestEventFiltering:
    def test_removed_event_suppressed_when_flag_false(self):
        previous = {"vm/901": "running"}
        current = {}
        events = diff_snapshots(previous, current, {})
        assert events[0]["event_type"] == "removed"
        # Filter pattern: skip if config[f"notify_{ev_type}"] is False
        config = {"notify_removed": False}
        filtered = [e for e in events if config.get(f"notify_{e['event_type']}", True)]
        assert filtered == []

    def test_started_event_suppressed_when_flag_false(self):
        previous = {"vm/100": "stopped"}
        current = {"vm/100": "running"}
        current_machines = {"vm/100": {"name": "web", "type": "vm", "node": "pve"}}
        events = diff_snapshots(previous, current, current_machines)
        assert events[0]["event_type"] == "started"
        config = {"notify_started": False}
        filtered = [e for e in events if config.get(f"notify_{e['event_type']}", True)]
        assert filtered == []

    def test_events_pass_when_flags_true(self):
        previous = {"vm/100": "running"}
        current = {"vm/100": "stopped"}
        current_machines = {"vm/100": {"name": "web", "type": "vm", "node": "pve"}}
        events = diff_snapshots(previous, current, current_machines)
        assert events[0]["event_type"] == "stopped"
        config = {"notify_stopped": True}
        filtered = [e for e in events if config.get(f"notify_{e['event_type']}", True)]
        assert len(filtered) == 1

    def test_mixed_flags_filter_correctly(self):
        previous = {"vm/1": "running", "vm/2": "stopped"}
        current = {"vm/1": "stopped", "vm/2": "running"}
        current_machines = {
            "vm/1": {"name": "A", "type": "vm", "node": "pve"},
            "vm/2": {"name": "B", "type": "vm", "node": "pve"},
        }
        events = diff_snapshots(previous, current, current_machines)
        event_types = {e["event_type"] for e in events}
        assert event_types == {"stopped", "started"}

        config = {"notify_started": False, "notify_stopped": True}
        filtered = [e for e in events if config.get(f"notify_{e['event_type']}", True)]
        assert len(filtered) == 1
        assert filtered[0]["event_type"] == "stopped"

    def test_default_true_when_key_absent(self):
        events = [{"event_type": "started", "machine_id": "vm/1"}]
        config = {}  # no keys set
        filtered = [e for e in events if config.get(f"notify_{e['event_type']}", True)]
        assert len(filtered) == 1


# ── Config persistence via sync endpoint ────────────────────────────────────


class TestNotifyConfigPersistence:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self._old_url = os.environ.get("PVE2_DB_URL")
        db_path = str(tmp_path / "test_notify.db")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{db_path}"
        from PVE2Services.core.wiki_service.app.main import app

        self.client = TestClient(app)
        self.client.post(
            "/admin/setup", json={"username": "admin", "new_password": "pve2admin"}
        )
        r = self.client.post(
            "/admin/login", json={"username": "admin", "password": "pve2admin"}
        )
        assert r.status_code == 200
        yield
        if self._old_url:
            os.environ["PVE2_DB_URL"] = self._old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def _get_csrf(self):
        return self.client.cookies.get("pve2_csrf", "")

    def _save_config(self, **overrides):
        body = {"enabled": True, **overrides}
        return self.client.post(
            "/api/plugins/pve2notify/config",
            json=body,
            headers={"X-CSRF-Token": self._get_csrf()},
        )

    def test_default_flags_in_fresh_config(self):
        r = self.client.get("/api/plugins/pve2notify/config")
        cfg = r.json()["config"]
        assert cfg.get("notify_started", True) is True
        assert cfg.get("notify_stopped", True) is True
        assert cfg.get("notify_added", True) is True
        assert cfg.get("notify_removed", True) is True

    def test_persist_and_reload_flags(self):
        self._save_config(notify_started=False, notify_removed=False)
        r = self.client.get("/api/plugins/pve2notify/config")
        cfg = r.json()["config"]
        assert cfg["notify_started"] is False
        assert cfg["notify_stopped"] is True
        assert cfg["notify_added"] is True
        assert cfg["notify_removed"] is False
