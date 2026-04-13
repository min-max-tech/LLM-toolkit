"""Tests for dashboard.settings port validation."""
from __future__ import annotations

import os
from unittest.mock import patch

from dashboard.settings import _validated_port


class TestValidatedPort:
    def test_valid_port(self):
        with patch.dict(os.environ, {"TEST_PORT": "8080"}):
            assert _validated_port("TEST_PORT", "9999") == "8080"

    def test_missing_env_returns_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PORT_MISSING", None)
            assert _validated_port("TEST_PORT_MISSING", "6680") == "6680"

    def test_non_numeric_returns_default(self):
        with patch.dict(os.environ, {"TEST_PORT": "abc"}):
            assert _validated_port("TEST_PORT", "6680") == "6680"

    def test_zero_returns_default(self):
        with patch.dict(os.environ, {"TEST_PORT": "0"}):
            assert _validated_port("TEST_PORT", "6680") == "6680"

    def test_port_too_high_returns_default(self):
        with patch.dict(os.environ, {"TEST_PORT": "70000"}):
            assert _validated_port("TEST_PORT", "6680") == "6680"

    def test_negative_returns_default(self):
        with patch.dict(os.environ, {"TEST_PORT": "-1"}):
            assert _validated_port("TEST_PORT", "6680") == "6680"

    def test_blocked_irc_port_still_returns_value(self):
        """IRC ports are warned about but still returned (user explicitly set them)."""
        with patch.dict(os.environ, {"TEST_PORT": "6667"}):
            assert _validated_port("TEST_PORT", "6680") == "6667"

    def test_boundary_port_1(self):
        with patch.dict(os.environ, {"TEST_PORT": "1"}):
            assert _validated_port("TEST_PORT", "6680") == "1"

    def test_boundary_port_65535(self):
        with patch.dict(os.environ, {"TEST_PORT": "65535"}):
            assert _validated_port("TEST_PORT", "6680") == "65535"

    def test_whitespace_stripped(self):
        with patch.dict(os.environ, {"TEST_PORT": "  8080  "}):
            assert _validated_port("TEST_PORT", "6680") == "8080"
