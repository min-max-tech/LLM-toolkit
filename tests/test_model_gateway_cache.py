"""Contract tests for model gateway TTL cache and X-Request-ID propagation."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _load_gateway_with_mock(mock_client):
    """Load the model-gateway module with httpx.AsyncClient already patched.

    The patch must be active during module load so that `from httpx import AsyncClient`
    binds to the mock — matching how test_model_gateway_contract.py works.
    """
    gateway_path = Path(__file__).resolve().parent.parent / "model-gateway" / "main.py"
    with patch("httpx.AsyncClient", return_value=mock_client):
        spec = importlib.util.spec_from_file_location("model_gateway_main_cache", gateway_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def _ok_client(model_names: list[str] | None = None):
    """httpx.AsyncClient mock that returns a valid Ollama /api/tags response."""
    names = model_names or ["deepseek-r1:7b"]
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"models": [{"name": n, "modified_at": 0} for n in names]}
    resp.raise_for_status = MagicMock()
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=resp)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


def _failing_client():
    """httpx.AsyncClient mock that always raises (simulates Ollama being unreachable)."""
    mock = AsyncMock()
    mock.get = AsyncMock(side_effect=Exception("Ollama unreachable"))
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


def test_model_list_returns_openai_format_with_provider_prefix():
    """GET /v1/models returns ollama/ prefixed model IDs."""
    gateway = _load_gateway_with_mock(_ok_client(["qwen2.5:7b"]))
    gateway._model_cache = []
    gateway._model_cache_ts = 0.0

    with patch("httpx.AsyncClient", return_value=_ok_client(["qwen2.5:7b"])):
        client = TestClient(gateway.app)
        r = client.get("/v1/models")

    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    assert "ollama/qwen2.5:7b" in ids


def test_model_list_served_from_cache_within_ttl():
    """
    Given: Cache is pre-populated with a model list and TTL has not expired
    When:  GET /v1/models is called (even with Ollama unreachable)
    Then:  Cached data is returned without contacting Ollama
    """
    gateway = _load_gateway_with_mock(_ok_client())
    cached_model = {"id": "ollama/cached-model:7b", "object": "model", "created": 0, "owned_by": "ollama"}
    gateway._model_cache = [cached_model]
    gateway._model_cache_ts = time.monotonic()  # just set — well within TTL
    gateway.MODEL_CACHE_TTL = 60.0

    # Even without mocking httpx (would fail if called), cache should be returned
    client = TestClient(gateway.app)
    r = client.get("/v1/models")

    assert r.status_code == 200
    assert r.json()["data"] == [cached_model], "Should return cached model list within TTL"


def test_model_list_stale_cache_served_when_provider_down():
    """
    Given: Stale cache exists (TTL expired) AND Ollama is unreachable
    When:  GET /v1/models is called
    Then:  Stale cache is returned rather than an empty list

    Note: the module is loaded with a *failing* client so that mod.AsyncClient
    (bound at import time via `from httpx import AsyncClient`) always raises.
    That way the stale-cache fallback branch is exercised.
    """
    # Load with a client that always fails — so mod.AsyncClient is the failing mock
    gateway = _load_gateway_with_mock(_failing_client())
    cached_model = {"id": "ollama/stale-model:7b", "object": "model", "created": 0, "owned_by": "ollama"}
    gateway._model_cache = [cached_model]
    gateway._model_cache_ts = 0.0  # TTL expired
    gateway.MODEL_CACHE_TTL = 60.0

    client = TestClient(gateway.app)
    r = client.get("/v1/models")

    assert r.status_code == 200
    assert r.json()["data"] == [cached_model], "Should return stale cache when provider is unreachable"


def test_cache_invalidated_via_delete_endpoint():
    """
    Given: Cache is populated
    When:  DELETE /v1/cache is called
    Then:  Cache is cleared; ok=True returned
    """
    gateway = _load_gateway_with_mock(_ok_client())
    gateway._model_cache = [{"id": "ollama/old-model", "object": "model", "created": 0, "owned_by": "ollama"}]
    gateway._model_cache_ts = 9_999_999_999.0
    gateway.MODEL_CACHE_TTL = 60.0

    client = TestClient(gateway.app)
    r = client.delete("/v1/cache")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert gateway._model_cache == []
    assert gateway._model_cache_ts == 0.0


def _streaming_client():
    """Mock for Ollama streaming chat: returns a valid SSE stream."""
    async def fake_aiter_lines():
        yield '{"message": {"role": "assistant", "content": "Hi"}, "done": false}'
        yield '{"message": {"role": "assistant", "content": "Hi there"}, "done": true, "eval_count": 2, "eval_duration": 500000000}'

    fake_resp = MagicMock()
    fake_resp.status_code = 200  # Required for resp.status_code >= 400 check in main.py
    fake_resp.aiter_lines = fake_aiter_lines
    fake_resp.__aenter__ = AsyncMock(return_value=fake_resp)
    fake_resp.__aexit__ = AsyncMock(return_value=None)

    mock = MagicMock()
    mock.stream = MagicMock(return_value=fake_resp)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


def test_request_id_generated_when_not_provided():
    """
    Given: POST /v1/chat/completions without X-Request-ID header
    When:  Request completes (streaming)
    Then:  Response headers contain an auto-generated X-Request-ID starting with 'req-'
    """
    gateway = _load_gateway_with_mock(_streaming_client())

    with patch("httpx.AsyncClient", return_value=_streaming_client()):
        client = TestClient(gateway.app)
        r = client.post(
            "/v1/chat/completions",
            json={"model": "deepseek-r1:7b", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )

    assert r.status_code == 200
    req_id = r.headers.get("X-Request-ID", "")
    assert req_id.startswith("req-"), f"Expected auto-generated req-<id>, got: {req_id!r}"


def test_request_id_echoed_when_provided():
    """
    Given: POST /v1/chat/completions with X-Request-ID: req-test-abc
    When:  Request completes (streaming)
    Then:  Response headers echo back X-Request-ID: req-test-abc
    """
    gateway = _load_gateway_with_mock(_streaming_client())

    with patch("httpx.AsyncClient", return_value=_streaming_client()):
        client = TestClient(gateway.app)
        r = client.post(
            "/v1/chat/completions",
            json={"model": "deepseek-r1:7b", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"X-Request-ID": "req-test-abc"},
        )

    assert r.status_code == 200
    assert r.headers.get("X-Request-ID") == "req-test-abc"
