"""Test SSRF validation in ops-controller model download."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock docker before loading ops-controller (avoids requiring docker package)
sys.modules.setdefault("docker", MagicMock())

_ops_controller_path = Path(__file__).resolve().parent.parent / "ops-controller" / "main.py"
_spec = importlib.util.spec_from_file_location("ops_controller_main", _ops_controller_path)
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)


class TestValidateDownloadUrl:
    """Verify _validate_download_url blocks SSRF vectors."""

    def test_allowed_host_passes(self, monkeypatch):
        monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [
            (2, 1, 6, "", ("104.18.0.1", 443)),
        ])
        oc._validate_download_url("https://huggingface.co/model.safetensors")

    def test_disallowed_host_rejected(self):
        with pytest.raises(ValueError, match="not in allowed list"):
            oc._validate_download_url("https://evil.com/model.safetensors")

    def test_private_ip_rejected(self, monkeypatch):
        monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ])
        with pytest.raises(ValueError, match="private/reserved IP"):
            oc._validate_download_url("https://huggingface.co/model.safetensors")

    def test_link_local_ip_rejected(self, monkeypatch):
        monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [
            (2, 1, 6, "", ("169.254.169.254", 443)),
        ])
        with pytest.raises(ValueError, match="private/reserved IP"):
            oc._validate_download_url("https://huggingface.co/model.safetensors")

    def test_empty_host_rejected(self):
        with pytest.raises(ValueError, match="Cannot parse hostname"):
            oc._validate_download_url("https:///no-host")
