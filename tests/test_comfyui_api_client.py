"""Test comfyui_api_client — ComfyUI HTTP client for orchestration."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from dashboard.comfyui_api_client import fetch_history, queue_prompt, wait_for_outputs

FAKE_URL = "http://comfyui:8188"
FAKE_PROMPT_ID = "abc-123"


def _run(coro):
    return asyncio.run(coro)


def _mock_async_client(mock_client):
    """Configure an AsyncMock to work as an async context manager."""
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestQueuePrompt:
    def test_success_returns_prompt_id(self):
        mock_response = httpx.Response(
            200, json={"prompt_id": FAKE_PROMPT_ID},
            request=httpx.Request("POST", f"{FAKE_URL}/prompt"),
        )
        with patch("dashboard.comfyui_api_client.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_async_client(AsyncMock())
            mock_client.post.return_value = mock_response
            mock_cls.return_value = mock_client

            result = _run(queue_prompt(FAKE_URL, {"1": {"class_type": "KSampler"}}))
            assert result == FAKE_PROMPT_ID
            mock_client.post.assert_called_once()

    def test_missing_prompt_id_raises(self):
        mock_response = httpx.Response(
            200, json={"status": "ok"},
            request=httpx.Request("POST", f"{FAKE_URL}/prompt"),
        )
        with patch("dashboard.comfyui_api_client.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_async_client(AsyncMock())
            mock_client.post.return_value = mock_response
            mock_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="missing prompt_id"):
                _run(queue_prompt(FAKE_URL, {}))

    def test_http_error_propagated(self):
        mock_response = httpx.Response(500, request=httpx.Request("POST", f"{FAKE_URL}/prompt"))
        with patch("dashboard.comfyui_api_client.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_async_client(AsyncMock())
            mock_client.post.return_value = mock_response
            mock_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                _run(queue_prompt(FAKE_URL, {}))


class TestFetchHistory:
    def test_success_returns_json(self):
        expected = {FAKE_PROMPT_ID: {"outputs": {"node1": {}}}}
        mock_response = httpx.Response(
            200, json=expected,
            request=httpx.Request("GET", f"{FAKE_URL}/history/{FAKE_PROMPT_ID}"),
        )
        with patch("dashboard.comfyui_api_client.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_async_client(AsyncMock())
            mock_client.get.return_value = mock_response
            mock_cls.return_value = mock_client

            result = _run(fetch_history(FAKE_PROMPT_ID, FAKE_URL))
            assert result == expected

    def test_404_returns_none(self):
        mock_response = httpx.Response(404, request=httpx.Request("GET", f"{FAKE_URL}/history/{FAKE_PROMPT_ID}"))
        with patch("dashboard.comfyui_api_client.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_async_client(AsyncMock())
            mock_client.get.return_value = mock_response
            mock_cls.return_value = mock_client

            result = _run(fetch_history(FAKE_PROMPT_ID, FAKE_URL))
            assert result is None

    def test_500_raises(self):
        mock_response = httpx.Response(500, request=httpx.Request("GET", f"{FAKE_URL}/history/{FAKE_PROMPT_ID}"))
        with patch("dashboard.comfyui_api_client.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_async_client(AsyncMock())
            mock_client.get.return_value = mock_response
            mock_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                _run(fetch_history(FAKE_PROMPT_ID, FAKE_URL))


class TestWaitForOutputs:
    def test_returns_when_outputs_available(self):
        entry = {"outputs": {"node1": {"images": []}}}
        with patch("dashboard.comfyui_api_client.fetch_history", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {FAKE_PROMPT_ID: entry}
            result = _run(wait_for_outputs(FAKE_PROMPT_ID, FAKE_URL, poll_interval_sec=0.01))
            assert result == entry

    def test_polls_until_outputs_appear(self):
        entry_no_outputs = {FAKE_PROMPT_ID: {"status": "running"}}
        entry_with_outputs = {FAKE_PROMPT_ID: {"outputs": {"node1": {}}}}
        with patch("dashboard.comfyui_api_client.fetch_history", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = [None, entry_no_outputs, entry_with_outputs]
            result = _run(wait_for_outputs(FAKE_PROMPT_ID, FAKE_URL, poll_interval_sec=0.01))
            assert result == entry_with_outputs[FAKE_PROMPT_ID]
            assert mock_fetch.call_count == 3

    def test_timeout_raises(self):
        with patch("dashboard.comfyui_api_client.fetch_history", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None
            with pytest.raises(TimeoutError, match="did not produce outputs"):
                _run(wait_for_outputs(FAKE_PROMPT_ID, FAKE_URL, max_wait_sec=0.05, poll_interval_sec=0.01))
