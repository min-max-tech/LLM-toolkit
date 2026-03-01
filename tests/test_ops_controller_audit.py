"""Test ops-controller audit event schema."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# Mock docker before loading ops-controller (avoids requiring docker package)
sys.modules["docker"] = MagicMock()

# Load ops-controller/main.py (folder has hyphen, not valid module name)
_ops_controller_path = Path(__file__).resolve().parent.parent / "ops-controller" / "main.py"
_spec = importlib.util.spec_from_file_location("ops_controller_main", _ops_controller_path)
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)


def test_audit_schema_fields():
    """_audit writes entries with ts, action, resource, actor, result, detail."""

    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "audit.log"
        oc.AUDIT_LOG_PATH = audit_path

        oc._audit("restart", "ollama", "ok", "")

        assert audit_path.exists()
        lines = audit_path.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert "ts" in entry
        assert entry["action"] == "restart"
        assert entry["resource"] == "ollama"
        assert entry["actor"] == "dashboard"
        assert entry["result"] == "ok"
        assert entry["detail"] == ""


def test_audit_schema_error_result():
    """_audit writes result=error and detail when provided."""

    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "audit.log"
        oc.AUDIT_LOG_PATH = audit_path

        oc._audit("restart", "ollama", "error", "container not found")

        lines = audit_path.read_text().strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["result"] == "error"
        assert entry["detail"] == "container not found"


def test_audit_schema_correlation_id():
    """_audit includes correlation_id when provided."""

    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "audit.log"
        oc.AUDIT_LOG_PATH = audit_path

        oc._audit("logs", "dashboard", "ok", "", correlation_id="req-abc123")

        lines = audit_path.read_text().strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["correlation_id"] == "req-abc123"
