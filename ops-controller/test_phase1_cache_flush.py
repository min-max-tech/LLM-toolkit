"""Tests for Phase 1: ComfyUI cache-flush on guardian resume.

When ``COMFYUI_FREE_AFTER_DRAIN=1`` (default), the guardian POSTs to
``comfyui:8188/free`` after the drain period elapses, BEFORE resuming
paused targets. This forces ComfyUI to drop cached weights so the
freed VRAM is actually available when llamacpp starts back up.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def reload_main(monkeypatch):
    from conftest import _install_docker_stub
    _install_docker_stub()
    monkeypatch.setenv("OPS_CONTROLLER_TOKEN", "test-token-for-test")

    def _go():
        import ops_controller.main as m
        importlib.reload(m)
        return m

    return _go


def test_free_after_drain_default_enabled(reload_main):
    """Cache-flush is on by default — bug class is silent and we want belt-and-suspenders default."""
    m = reload_main()
    assert m.COMFYUI_FREE_AFTER_DRAIN is True


def test_free_after_drain_can_be_disabled(monkeypatch, reload_main):
    """Operators can opt out (e.g. when intentionally keeping ComfyUI hot for back-to-back runs)."""
    monkeypatch.setenv("COMFYUI_FREE_AFTER_DRAIN", "0")
    m = reload_main()
    assert m.COMFYUI_FREE_AFTER_DRAIN is False


def test_free_after_drain_truthy_strings(monkeypatch, reload_main):
    """Accept the same truthy spellings as COMFYUI_SERIALIZE_LLAMACPP."""
    for v in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("COMFYUI_FREE_AFTER_DRAIN", v)
        m = reload_main()
        assert m.COMFYUI_FREE_AFTER_DRAIN is True, f"value {v!r} should be truthy"


def test_comfyui_free_cache_posts_to_free_endpoint(reload_main, monkeypatch):
    """The helper POSTs ``{unload_models, free_memory}`` to ComfyUI's /free endpoint."""
    import httpx
    m = reload_main()

    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    ok = m._comfyui_free_cache()

    assert ok is True
    assert captured["url"].endswith("/free")
    assert captured["json"]["unload_models"] is True
    assert captured["json"]["free_memory"] is True
    assert captured["timeout"] is not None


def test_comfyui_free_cache_returns_false_on_error(reload_main, monkeypatch):
    """Network/HTTP failures don't crash the guardian — they just fail-open and the
    resume cycle continues. We log via audit but don't propagate."""
    import httpx
    m = reload_main()

    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    assert m._comfyui_free_cache() is False


def test_status_dict_exposes_free_after_drain_flag(reload_main, monkeypatch):
    """Status dict surfaces the toggle so operators can see it via /guardian/status."""
    monkeypatch.setenv("COMFYUI_FREE_AFTER_DRAIN", "1")
    m = reload_main()
    assert m._guardian_status["free_after_drain"] is True
