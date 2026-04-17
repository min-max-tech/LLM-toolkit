"""Unit tests for ops-controller stats helpers and /stats/services endpoint."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("docker", MagicMock())

_path = Path(__file__).resolve().parent.parent / "ops-controller" / "main.py"
_spec = importlib.util.spec_from_file_location("ops_controller_main", _path)
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)


def test_cpu_pct_from_stats_basic():
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 1_000_000_000}, "system_cpu_usage": 10_000_000_000, "online_cpus": 4},
        "precpu_stats": {"cpu_usage": {"total_usage": 750_000_000}, "system_cpu_usage": 9_000_000_000},
    }
    # cpu_delta=250M, system_delta=1B, cpus=4 → (.25)*4*100 = 100.0
    assert oc._cpu_pct_from_stats(stats) == 100.0


def test_cpu_pct_from_stats_zero_system_delta():
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 1}, "system_cpu_usage": 100, "online_cpus": 2},
        "precpu_stats": {"cpu_usage": {"total_usage": 1}, "system_cpu_usage": 100},
    }
    assert oc._cpu_pct_from_stats(stats) == 0.0


def test_cpu_pct_from_stats_missing_fields():
    assert oc._cpu_pct_from_stats({}) == 0.0
    assert oc._cpu_pct_from_stats({"cpu_stats": {}}) == 0.0


def test_mem_from_stats_cgroup_v2():
    # docker stats subtracts inactive_file (v2) from usage
    stats = {"memory_stats": {
        "usage": 2_000_000_000,
        "stats": {"inactive_file": 500_000_000},
        "limit": 10_000_000_000,
    }}
    gb, pct = oc._mem_from_stats(stats)
    assert gb == 1.5
    assert pct == 15.0


def test_mem_from_stats_cgroup_v1_fallback_to_cache():
    stats = {"memory_stats": {
        "usage": 1_500_000_000,
        "stats": {"cache": 500_000_000},
        "limit": 4_000_000_000,
    }}
    gb, pct = oc._mem_from_stats(stats)
    assert gb == 1.0
    assert pct == 25.0


def test_mem_from_stats_empty():
    assert oc._mem_from_stats({}) == (0.0, 0.0)
    assert oc._mem_from_stats({"memory_stats": {}}) == (0.0, 0.0)