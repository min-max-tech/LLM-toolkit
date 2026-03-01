"""Test dashboard /api/health endpoint."""
import os
import sys

# Ensure dashboard is importable when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from dashboard.app import app

client = TestClient(app)


def test_health_returns_200():
    """GET /api/health returns 200."""
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_has_ok_and_services():
    """GET /api/health returns ok boolean and services array."""
    r = client.get("/api/health")
    data = r.json()
    assert "ok" in data
    assert isinstance(data["ok"], bool)
    assert "services" in data
    assert isinstance(data["services"], list)
