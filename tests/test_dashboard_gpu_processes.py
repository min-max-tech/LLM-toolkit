"""Tests for GPU process label resolution and /api/hardware/gpu-processes endpoint."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import psutil
import pytest
from fastapi.testclient import TestClient


def _make_proc(cmdline_list: list[str], name: str) -> MagicMock:
    p = MagicMock()
    p.cmdline.return_value = cmdline_list
    p.name.return_value = name
    return p


def test_pid_label_llm() -> None:
    import dashboard.app as app
    with patch("psutil.Process", return_value=_make_proc(["/app/llama-server", "--host", "0.0.0.0"], "llama-server")):
        assert app._pid_to_service_label(1234) == "LLM"


def test_pid_label_llama_underscore() -> None:
    import dashboard.app as app
    with patch("psutil.Process", return_value=_make_proc(["llama_server", "--model", "foo.gguf"], "llama_server")):
        assert app._pid_to_service_label(1235) == "LLM"


def test_pid_label_comfyui() -> None:
    import dashboard.app as app
    with patch("psutil.Process", return_value=_make_proc(["python3.12", "/root/ComfyUI/main.py"], "python3.12")):
        assert app._pid_to_service_label(5678) == "ComfyUI"


def test_pid_label_embed() -> None:
    import dashboard.app as app
    with patch("psutil.Process", return_value=_make_proc(["python3.12", "-m", "embed_server"], "python3.12")):
        assert app._pid_to_service_label(9012) == "Embed"


def test_pid_label_fallback_python() -> None:
    import dashboard.app as app
    with patch("psutil.Process", return_value=_make_proc(["python3.12", "unknown_service.py"], "python3.12")):
        assert app._pid_to_service_label(3456) == "Python"


def test_pid_label_non_python_truncates() -> None:
    import dashboard.app as app
    with patch("psutil.Process", return_value=_make_proc(["some-long-process-name", "--flag"], "some-long-process-name")):
        result = app._pid_to_service_label(7890)
        assert len(result) <= 12


def test_pid_label_process_gone() -> None:
    import dashboard.app as app
    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(pid=9999)):
        assert app._pid_to_service_label(9999) == "pid:9999"


def test_pid_label_access_denied() -> None:
    import dashboard.app as app
    with patch("psutil.Process", side_effect=psutil.AccessDenied(pid=8888)):
        assert app._pid_to_service_label(8888) == "pid:8888"
