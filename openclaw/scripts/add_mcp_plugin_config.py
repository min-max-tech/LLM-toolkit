#!/usr/bin/env python3
"""Add MCP plugin config to openclaw.json after plugin-install. Run after openclaw-plugin-install."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Plugin ID from openclaw-mcp-bridge (github:fsaint/openclaw-mcp-bridge) manifest
MCP_PLUGIN_ID = "plugin-mcp-client"
MCP_PLUGIN_CONFIG = {
    "enabled": True,
    "config": {
        "servers": {
            "gateway": {"url": "http://mcp-gateway:8811/mcp"}
        },
        "debug": False,
    },
}


def main() -> int:
    config_path = Path("/config/openclaw.json")
    if not config_path.exists():
        return 0

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"add_mcp_plugin_config: skip (read error): {e}", file=sys.stderr)
        return 0

    plugins = data.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        return 0
    entries = plugins.setdefault("entries", {})
    if not isinstance(entries, dict):
        return 0

    if MCP_PLUGIN_ID in entries:
        return 0  # Already configured

    entries[MCP_PLUGIN_ID] = MCP_PLUGIN_CONFIG
    plugins["enabled"] = True

    try:
        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"add_mcp_plugin_config: added {MCP_PLUGIN_ID} to plugins.entries")
    except OSError as e:
        print(f"add_mcp_plugin_config: write failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
