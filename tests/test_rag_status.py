"""Contract tests for dashboard GET /api/rag/status."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import dashboard.app as dashboard_app

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {"points_count": 42, "status": "green"},
    }
    mock_inner = AsyncMock()
    mock_inner.get = AsyncMock(return_value=mock_resp)
    mock_inner.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_inner.__aexit__ = AsyncMock(return_value=None)

    with patch.object(dashboard_app, "AsyncClient", return_value=mock_inner):
        yield TestClient(dashboard_app.app)


def test_rag_status_returns_ok_and_counts(client):
    """GET /api/rag/status returns ok, collection, points_count when Qdrant responds."""
    r = client.get("/api/rag/status")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("collection") == "documents"
    assert data.get("points_count") == 42
    assert data.get("status") == "green"


def test_rag_status_empty_collection_404():
    """404 from Qdrant means collection missing — dashboard reports empty collection."""
    import dashboard.app as dashboard_app

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_inner = AsyncMock()
    mock_inner.get = AsyncMock(return_value=mock_resp)
    mock_inner.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_inner.__aexit__ = AsyncMock(return_value=None)

    with patch.object(dashboard_app, "AsyncClient", return_value=mock_inner):
        c = TestClient(dashboard_app.app)
        r = c.get("/api/rag/status")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("points_count") == 0
    assert data.get("status") == "empty"
