"""Tests for the example_plugin template endpoints."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PVE2Services.plugins import example_plugin


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PVE2_DB_URL", f"sqlite:///{tmp_path / 'example_plugin.db'}")
    app = FastAPI()
    example_plugin.load_plugin(app)
    return TestClient(app)


def test_info_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.get("/api/plugins/example_plugin/info")
    assert response.status_code == 200
    body = response.json()
    assert body["plugin"] == "example_plugin"
    assert body["version"] == "0.1.0"


def test_config_endpoints(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/plugins/example_plugin/config").status_code == 200
    saved = client.post(
        "/api/plugins/example_plugin/config",
        json={"api_endpoint": "https://example.invalid", "enabled": True},
    )
    assert saved.status_code == 200
    assert saved.json()["saved"] is True


def test_sync_requires_enabled(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # Not configured/enabled -> sync reports it skipped rather than failing.
    assert client.post("/api/plugins/example_plugin/sync").status_code == 200
