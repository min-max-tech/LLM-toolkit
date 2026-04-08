from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_DIST = REPO_ROOT / "openclaw" / "extensions" / "openclaw-mcp-bridge" / "dist" / "index.js"


def test_mcp_bridge_prompt_prefers_flat_tools_when_enabled():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    assert "Prefer direct flat MCP tools like" in text
    assert "Do not wrap a flat tool call inside" in text
    assert "only as a legacy fallback when a flat tool is unavailable" in text
    assert "Never run \\`${prefix}__*\\` through \\`exec\\`, shell, \\`sh\\`, or \\`bash\\`." in text
    assert "Never include raw `<|tool_call|>`, `<|tool_response|>`, `<channel|>`, or thought text inside tool arguments." in text


def test_mcp_bridge_recovers_malformed_gateway_call_payloads():
    text = BRIDGE_DIST.read_text(encoding="utf-8")

    assert "function recoverProxyInvocation(params)" in text
    assert "mcp-client: recovered malformed" in text
    assert '.replace(/\\\\"/g, \'"\')' in text
    assert 'extractBalancedObject(combined, /gateway__call\\s*\\(/i)' in text
