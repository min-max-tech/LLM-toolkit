"""Unit tests for dashboard dependency HTTP probes (M7)."""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_mock_client(status_code: int) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    client = MagicMock()
    client.get = AsyncMock(return_value=mock_resp)
    return client


def test_mcp_gateway_http_400_counts_as_reachable():
    """Naive GET /mcp returns 400; gateway is still up for MCP clients."""
    from dashboard.dependency_registry import _probe_one

    client = _make_mock_client(400)
    ok, _lat, err = asyncio.run(
        _probe_one("http://mcp-gateway:8811/mcp", client, entry_id="mcp-gateway")
    )
    assert ok is True
    assert err is None


def test_other_services_http_400_still_fails():
    from dashboard.dependency_registry import _probe_one

    client = _make_mock_client(400)
    ok, _lat, err = asyncio.run(
        _probe_one("http://model-gateway:11435/health", client, entry_id="model-gateway")
    )
    assert ok is False
    assert err == "HTTP 400"
