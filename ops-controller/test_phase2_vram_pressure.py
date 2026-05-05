"""Tests for Phase 2: VRAM-pressure independent watchdog.

Independent of the ComfyUI-queue-based guardian: when free VRAM drops below
``OPS_VRAM_PRESSURE_GB`` for a sustained period (regardless of ComfyUI
state), POST to ComfyUI's /free to drop cached weights and recover headroom.
Hysteresis: stays in "pressure" state until free VRAM rises above
``OPS_VRAM_RECOVERY_GB`` so we don't flap on transient allocations.

This catches the failure mode where the queue-driven guardian's resume
cycle technically completed but VRAM was already saturated by another
consumer (e.g. ai-toolkit training, ComfyUI cache that survived a /free
call, etc.) and llamacpp is now stuck in slow-decode mode anyway.
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


def test_pressure_trigger_disabled_by_default(reload_main):
    """OPS_VRAM_PRESSURE_GB=0 means the watchdog is off — opt-in feature."""
    m = reload_main()
    assert m.OPS_VRAM_PRESSURE_GB == 0.0
    assert m._vram_pressure_enabled() is False


def test_pressure_trigger_enabled_when_threshold_set(monkeypatch, reload_main):
    """A positive threshold turns the watchdog on."""
    monkeypatch.setenv("OPS_VRAM_PRESSURE_GB", "2.5")
    m = reload_main()
    assert m.OPS_VRAM_PRESSURE_GB == 2.5
    assert m._vram_pressure_enabled() is True


def test_recovery_threshold_defaults_to_pressure_plus_two(monkeypatch, reload_main):
    """Sensible default: recovery is 2 GB above pressure to avoid flapping."""
    monkeypatch.setenv("OPS_VRAM_PRESSURE_GB", "3.0")
    m = reload_main()
    assert m.OPS_VRAM_RECOVERY_GB == 5.0


def test_recovery_threshold_explicit_override(monkeypatch, reload_main):
    """Operators can set both thresholds independently."""
    monkeypatch.setenv("OPS_VRAM_PRESSURE_GB", "2.0")
    monkeypatch.setenv("OPS_VRAM_RECOVERY_GB", "8.0")
    m = reload_main()
    assert m.OPS_VRAM_RECOVERY_GB == 8.0


def test_recovery_threshold_must_exceed_pressure(monkeypatch, reload_main):
    """If user misconfigures recovery <= pressure, fall back to safe pressure+2 default
    rather than letting the watchdog flap on every poll."""
    monkeypatch.setenv("OPS_VRAM_PRESSURE_GB", "5.0")
    monkeypatch.setenv("OPS_VRAM_RECOVERY_GB", "3.0")  # invalid: below pressure
    m = reload_main()
    assert m.OPS_VRAM_RECOVERY_GB == 7.0  # forced to pressure + 2


def test_pressure_state_machine_transitions(monkeypatch, reload_main):
    """Three-state machine: idle → pressure → idle. Each transition is one
    `_vram_pressure_step()` call, given a free-VRAM reading."""
    monkeypatch.setenv("OPS_VRAM_PRESSURE_GB", "2.0")
    monkeypatch.setenv("OPS_VRAM_RECOVERY_GB", "5.0")
    m = reload_main()

    # Stays idle while VRAM has headroom
    state = "idle"
    state, action = m._vram_pressure_step(state, free_gb=10.0)
    assert state == "idle"
    assert action is None

    # Drops below pressure → fire (action = "free_cache")
    state, action = m._vram_pressure_step(state, free_gb=1.5)
    assert state == "pressure"
    assert action == "free_cache"

    # Stays in pressure until recovery threshold
    state, action = m._vram_pressure_step(state, free_gb=3.0)
    assert state == "pressure"
    assert action is None

    state, action = m._vram_pressure_step(state, free_gb=4.0)
    assert state == "pressure"
    assert action is None

    # Crosses recovery → back to idle
    state, action = m._vram_pressure_step(state, free_gb=6.0)
    assert state == "idle"
    assert action is None

    # Re-trigger if pressure returns
    state, action = m._vram_pressure_step(state, free_gb=1.0)
    assert state == "pressure"
    assert action == "free_cache"


def test_pressure_step_ignores_unmeasurable_vram(monkeypatch, reload_main):
    """If VRAM probe returns None (dashboard unreachable), don't change state — fail-open."""
    monkeypatch.setenv("OPS_VRAM_PRESSURE_GB", "2.0")
    m = reload_main()
    state, action = m._vram_pressure_step("idle", free_gb=None)
    assert state == "idle"
    assert action is None
    state, action = m._vram_pressure_step("pressure", free_gb=None)
    assert state == "pressure"
    assert action is None


def test_status_dict_exposes_pressure_state(monkeypatch, reload_main):
    """Dashboard / curl /guardian/status can see the watchdog config + current state."""
    monkeypatch.setenv("OPS_VRAM_PRESSURE_GB", "2.0")
    monkeypatch.setenv("OPS_VRAM_RECOVERY_GB", "5.0")
    m = reload_main()
    s = m._guardian_status
    assert s["vram_pressure_enabled"] is True
    assert s["vram_pressure_gb"] == 2.0
    assert s["vram_recovery_gb"] == 5.0
    assert s["vram_pressure_state"] == "idle"
