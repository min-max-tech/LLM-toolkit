"""Tests for OpenClaw MCP bridge config sync helpers."""

import importlib.util
import json
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parent.parent / "openclaw" / "scripts" / "add_mcp_plugin_config.py"
    spec = importlib.util.spec_from_file_location("add_mcp_plugin_config", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ensure_plugin_manifest_updates_existing_file():
    mod = _load_module()
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "mcp_plugin_config_tmp"
    fixture_root.mkdir(parents=True, exist_ok=True)
    manifest_path = fixture_root / "openclaw.plugin.json"
    try:
        mod.EXTENSIONS_DIR = fixture_root
        manifest_path.write_text('{"id":"old"}', encoding="utf-8")

        mod._ensure_plugin_manifest()

        rendered = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert rendered["id"] == mod.MCP_PLUGIN_ID
        assert "flatTools" in rendered["configSchema"]["properties"]
        assert "injectSchemas" in rendered["configSchema"]["properties"]
    finally:
        if manifest_path.exists():
            manifest_path.unlink()


def test_normalize_mcp_bridge_servers_enables_flat_tools():
    mod = _load_module()
    data = {
        "plugins": {
            "entries": {
                mod.MCP_PLUGIN_ID: {
                    "config": {
                        "servers": {
                            "gateway": {
                                "url": "http://wrong",
                                "connectTimeoutMs": 1,
                                "requestTimeoutMs": 2,
                            },
                            "comfyui": {"url": "http://old"},
                        },
                        "flatTools": True,
                        "injectSchemas": True,
                    }
                }
            }
        }
    }

    modified = mod.normalize_mcp_bridge_servers(data)

    cfg = data["plugins"]["entries"][mod.MCP_PLUGIN_ID]["config"]
    assert modified is True
    assert "comfyui" not in cfg["servers"]
    assert cfg["servers"]["gateway"]["url"] == mod._mcp_url
    assert cfg["flatTools"] is True
    assert cfg["injectSchemas"] is False
