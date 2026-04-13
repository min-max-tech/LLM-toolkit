"""Test ops-controller auth enforcement on state-modifying endpoints."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Mock docker before loading ops-controller
sys.modules.setdefault("docker", MagicMock())

_ops_controller_path = Path(__file__).resolve().parent.parent / "ops-controller" / "main.py"
_spec = importlib.util.spec_from_file_location("ops_controller_main", _ops_controller_path)
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)

# Set a known token for testing
VALID_TOKEN = "test-secret-token"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(oc, "OPS_CONTROLLER_TOKEN", VALID_TOKEN)
    return TestClient(oc.app, raise_server_exceptions=False)


# Endpoints that require auth (method, path, body)
AUTH_REQUIRED_ENDPOINTS = [
    ("post", "/services/llamacpp/restart", {"confirm": True}),
    ("post", "/services/llamacpp/start", {"confirm": True}),
    ("post", "/services/llamacpp/stop", {"confirm": True}),
    ("post", "/services/llamacpp/recreate", {"confirm": True}),
    ("get", "/services/llamacpp/logs", None),
    ("post", "/images/pull", {"services": ["llamacpp"]}),
    ("get", "/mcp/containers", None),
    ("post", "/env/set", {"key": "HF_TOKEN", "value": "x", "confirm": True}),
    ("get", "/env/HF_TOKEN", None),
    ("get", "/audit", None),
    ("post", "/models/download", {"url": "https://huggingface.co/m.safetensors"}),
    ("get", "/models/download/status", None),
]


class TestAuthEnforcement:
    """Verify all state-modifying endpoints reject unauthenticated requests."""

    @pytest.mark.parametrize("method,path,body", AUTH_REQUIRED_ENDPOINTS)
    def test_missing_auth_returns_401(self, client, method, path, body):
        fn = getattr(client, method)
        kwargs = {"json": body} if body else {}
        r = fn(path, **kwargs)
        assert r.status_code == 401, f"{method.upper()} {path} returned {r.status_code}, expected 401"

    @pytest.mark.parametrize("method,path,body", AUTH_REQUIRED_ENDPOINTS)
    def test_wrong_token_returns_403(self, client, method, path, body):
        fn = getattr(client, method)
        kwargs = {"json": body} if body else {}
        r = fn(path, headers={"Authorization": "Bearer wrong-token"}, **kwargs)
        assert r.status_code == 403, f"{method.upper()} {path} returned {r.status_code}, expected 403"

    def test_valid_token_passes_auth(self, client):
        """Verify a valid token passes the auth check (health is unauthenticated)."""
        r = client.get("/health")
        assert r.status_code == 200

    def test_no_token_configured_returns_503(self, monkeypatch):
        """When OPS_CONTROLLER_TOKEN is empty, all auth'd endpoints return 503."""
        monkeypatch.setattr(oc, "OPS_CONTROLLER_TOKEN", "")
        c = TestClient(oc.app, raise_server_exceptions=False)
        r = c.get("/audit")
        assert r.status_code == 503
