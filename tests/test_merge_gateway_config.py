"""Unit tests for openclaw/scripts/merge_gateway_config.py (channel SecretRef injection)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "openclaw" / "scripts" / "merge_gateway_config.py"
_spec = importlib.util.spec_from_file_location("merge_gateway_config", _SCRIPT)
assert _spec and _spec.loader
mg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mg)


def test_secret_ref_shape() -> None:
    assert mg._secret_ref("FOO") == {"source": "env", "id": "FOO"}


def test_inject_discord_from_discord_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    data: dict = {"channels": {"discord": {"enabled": True, "token": "plaintext"}}}
    assert mg._inject_channel_secret_refs(data) is True
    assert data["channels"]["discord"]["token"] == {"source": "env", "id": "DISCORD_BOT_TOKEN"}


def test_inject_discord_from_discord_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "y")
    data: dict = {"channels": {"discord": {}}}
    assert mg._inject_channel_secret_refs(data) is True
    assert data["channels"]["discord"]["token"] == {"source": "env", "id": "DISCORD_BOT_TOKEN"}


def test_inject_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg")
    data: dict = {"channels": {"telegram": {"enabled": True, "botToken": "old"}}}
    assert mg._inject_channel_secret_refs(data) is True
    assert data["channels"]["telegram"]["botToken"] == {"source": "env", "id": "TELEGRAM_BOT_TOKEN"}


def test_no_env_leaves_tokens_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    data: dict = {"channels": {"discord": {"token": "keep-me"}, "telegram": {"botToken": "keep-tg"}}}
    assert mg._inject_channel_secret_refs(data) is False


def test_channels_not_dict_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    data: dict = {"channels": "broken"}
    assert mg._inject_channel_secret_refs(data) is False
