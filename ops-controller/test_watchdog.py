"""Tests for the Hermes self-heal watchdog.

The watchdog is structured for testability:

* ``_watchdog_decision`` is a pure function — synchronous, no I/O.
* ``_watchdog_iteration`` runs one cycle synchronously; the asyncio loop
  just calls it and sleeps.

Tests exercise these directly; the asyncio scheduler is not involved.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock


def _make_container(name, service, status="running", finished_at=""):
    c = MagicMock()
    c.name = name
    c.labels = {
        "com.docker.compose.service": service,
        "com.docker.compose.project": "ordo-ai-stack",
    }
    c.status = status
    c.attrs = {"State": {"FinishedAt": finished_at}}
    return c


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _patch_audit_log(monkeypatch, m, audit_path):
    from ops_controller.audit import AuditLog
    monkeypatch.setattr(m, "_audit_log", AuditLog(audit_path))


def _read_audit(audit_path):
    if not audit_path.exists():
        return []
    return [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]


# ── Pure decision function ───────────────────────────────────────────────────


def test_decision_running_skips():
    from ops_controller.main import _watchdog_decision
    c = _make_container("x", "hermes-gateway", status="running")
    assert _watchdog_decision(c, datetime.now(UTC), 60)[0] == "skip-running"


def test_decision_starting_skips():
    from ops_controller.main import _watchdog_decision
    c = _make_container("x", "hermes-gateway", status="starting")
    assert _watchdog_decision(c, datetime.now(UTC), 60)[0] == "skip-running"


def test_decision_act_after_grace():
    from ops_controller.main import _watchdog_decision
    now = datetime.now(UTC)
    c = _make_container("x", "hermes-gateway", "exited",
                        finished_at=_iso(now - timedelta(seconds=120)))
    decision, detail = _watchdog_decision(c, now, 60)
    assert decision == "act"
    assert "120s" in detail


def test_decision_skip_during_grace():
    from ops_controller.main import _watchdog_decision
    now = datetime.now(UTC)
    c = _make_container("x", "hermes-gateway", "exited",
                        finished_at=_iso(now - timedelta(seconds=30)))
    assert _watchdog_decision(c, now, 60)[0] == "skip-grace"


def test_decision_no_finish_at():
    from ops_controller.main import _watchdog_decision
    c = _make_container("x", "hermes-gateway", "exited",
                        finished_at="0001-01-01T00:00:00Z")
    assert _watchdog_decision(c, datetime.now(UTC), 60)[0] == "skip-no-finish"


def test_decision_empty_finish_at():
    from ops_controller.main import _watchdog_decision
    c = _make_container("x", "hermes-gateway", "exited", finished_at="")
    assert _watchdog_decision(c, datetime.now(UTC), 60)[0] == "skip-no-finish"


def test_decision_malformed_finish_at():
    from ops_controller.main import _watchdog_decision
    c = _make_container("x", "hermes-gateway", "exited", finished_at="not-a-date")
    assert _watchdog_decision(c, datetime.now(UTC), 60)[0] == "skip-bad-finish"


# ── Pause helper ─────────────────────────────────────────────────────────────


def test_pause_helper_reflects_file(tmp_path, monkeypatch):
    import ops_controller.main as m
    paused = tmp_path / "pause"
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_PAUSE_FILE", str(paused))
    assert m._watchdog_paused() is False
    paused.touch()
    assert m._watchdog_paused() is True
    paused.unlink()
    assert m._watchdog_paused() is False


# ── Iteration ────────────────────────────────────────────────────────────────


def test_iteration_paused_writes_one_audit(tmp_path, monkeypatch):
    import ops_controller.main as m
    audit_path = tmp_path / "audit.jsonl"
    paused = tmp_path / "pause"
    paused.touch()
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_PAUSE_FILE", str(paused))
    _patch_audit_log(monkeypatch, m, audit_path)

    m._watchdog_iteration()

    entries = _read_audit(audit_path)
    assert len(entries) == 1
    assert entries[0]["action"] == "watchdog.paused"


def test_iteration_skip_running_writes_no_audit(tmp_path, monkeypatch):
    """Healthy state must NOT write audit entries (would flood the log)."""
    import ops_controller.main as m
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_PAUSE_FILE", str(tmp_path / "no-such"))
    _patch_audit_log(monkeypatch, m, audit_path)

    fake_client = MagicMock()
    fake_client.containers.list.return_value = [
        _make_container("hg", "hermes-gateway", "running"),
        _make_container("hd", "hermes-dashboard", "running"),
    ]
    monkeypatch.setattr(m, "_docker_client", lambda: fake_client)

    m._watchdog_iteration()
    assert _read_audit(audit_path) == []


def test_iteration_acts_on_exited_after_grace(tmp_path, monkeypatch):
    import ops_controller.main as m
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_PAUSE_FILE", str(tmp_path / "no-such"))
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_GRACE_SECONDS", 60.0)
    _patch_audit_log(monkeypatch, m, audit_path)

    finished = datetime.now(UTC) - timedelta(seconds=300)
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [
        _make_container("hg", "hermes-gateway", "exited", finished_at=_iso(finished)),
    ]
    monkeypatch.setattr(m, "_docker_client", lambda: fake_client)
    monkeypatch.setattr(m, "_run_compose",
                        lambda verb, svc: MagicMock(returncode=0, stderr="", stdout=""))

    m._watchdog_iteration()

    entries = _read_audit(audit_path)
    actions = [e["action"] for e in entries]
    assert "watchdog.acted" in actions
    acted = next(e for e in entries if e["action"] == "watchdog.acted")
    assert acted["target"] == "hermes-gateway"
    assert acted["result"] == "ok"


def test_iteration_records_failure_on_compose_up_error(tmp_path, monkeypatch):
    """Regression: the original code crashed with TypeError on this path."""
    import ops_controller.main as m
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_PAUSE_FILE", str(tmp_path / "no-such"))
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_GRACE_SECONDS", 60.0)
    _patch_audit_log(monkeypatch, m, audit_path)

    finished = datetime.now(UTC) - timedelta(seconds=300)
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [
        _make_container("hg", "hermes-gateway", "exited", finished_at=_iso(finished)),
    ]
    monkeypatch.setattr(m, "_docker_client", lambda: fake_client)
    monkeypatch.setattr(m, "_run_compose",
                        lambda verb, svc: MagicMock(returncode=1, stderr="boom", stdout=""))

    m._watchdog_iteration()

    entries = _read_audit(audit_path)
    assert len(entries) == 1
    assert entries[0]["action"] == "watchdog.acted"
    assert entries[0]["result"] == "fail"
    assert "boom" in entries[0]["stderr"]
    assert entries[0]["rc"] == 1


def test_iteration_skip_grace_does_not_call_compose(tmp_path, monkeypatch):
    import ops_controller.main as m
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_PAUSE_FILE", str(tmp_path / "no-such"))
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_GRACE_SECONDS", 60.0)
    _patch_audit_log(monkeypatch, m, audit_path)

    finished = datetime.now(UTC) - timedelta(seconds=10)  # within grace
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [
        _make_container("hg", "hermes-gateway", "exited", finished_at=_iso(finished)),
    ]
    monkeypatch.setattr(m, "_docker_client", lambda: fake_client)
    called = []
    monkeypatch.setattr(m, "_run_compose",
                        lambda *a, **kw: called.append((a, kw)) or MagicMock(returncode=0))

    m._watchdog_iteration()

    assert called == []
    entries = _read_audit(audit_path)
    assert len(entries) == 1
    assert entries[0]["action"] == "watchdog.skipped-grace"
    assert entries[0]["result"] == "ok"


def test_iteration_handles_docker_error(tmp_path, monkeypatch):
    """If the docker client fails, the iteration should log and return — not raise."""
    import ops_controller.main as m
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(m, "OPS_HERMES_WATCHDOG_PAUSE_FILE", str(tmp_path / "no-such"))
    _patch_audit_log(monkeypatch, m, audit_path)

    def _boom():
        raise RuntimeError("docker daemon unreachable")
    monkeypatch.setattr(m, "_docker_client", _boom)

    m._watchdog_iteration()  # must not raise
    assert _read_audit(audit_path) == []
