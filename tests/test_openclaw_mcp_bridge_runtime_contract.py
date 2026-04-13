"""Contract checks for the forked OpenClaw MCP bridge runtime."""
from __future__ import annotations

from pathlib import Path


def test_bridge_runtime_registers_discover_tool_and_compact_contract():
    bridge_path = (
        Path(__file__).resolve().parent.parent
        / "openclaw"
        / "extensions"
        / "openclaw-mcp-bridge"
        / "dist"
        / "index.js"
    )
    source = bridge_path.read_text(encoding="utf-8")

    assert "__discover" in source
    assert "MCP Tool Contract" in source
    assert "do not know the exact tool name or arguments" in source
    assert "registered discovery tool" in source
    assert 'tool: Type.String(' in source
    assert 'toolName' not in source.split("Type.Object")[1].split("}),")[0]
    assert 'missing required tool name for ${prefix}__call' in source
    assert 'autoDiscovered: true' in source
    assert 'Example: \\`${prefix}__call({' in source
    assert '.replace(/\\]\\s*$/, "}")' in source
    assert '.replace(/([{,]\\s*)([A-Za-z_][A-Za-z0-9_]*)(\\s*:)/g, \'$1"$2"$3\')' in source


def test_bridge_defaults_keep_schema_injection_off():
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "openclaw"
        / "extensions"
        / "openclaw-mcp-bridge"
        / "dist"
        / "config-schema.js"
    )
    plugin_manifest_path = (
        Path(__file__).resolve().parent.parent
        / "openclaw"
        / "extensions"
        / "openclaw-mcp-bridge"
        / "openclaw.plugin.json"
    )

    schema_source = schema_path.read_text(encoding="utf-8")
    manifest_source = plugin_manifest_path.read_text(encoding="utf-8")

    assert 'default: false' in schema_source
    assert '"injectSchemas"' in manifest_source
    assert '"default": false' in manifest_source
