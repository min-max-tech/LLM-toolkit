# OpenClaw Gateway Tool Troubleshooting

## "Missing raw parameter" (config.patch)

**Cause:** The gateway tool's `config.patch` action requires a `raw` parameter — a JSON string of the partial config to merge. The agent invoked config.patch without supplying it.

**Fix:** When using `gateway` with `action: "config.patch"`, the agent must pass:
- `raw` — JSON string of the config fragment to merge (e.g. `'{"agents":{"defaults":{"model":{"primary":"gateway/ollama/deepseek-r1:7b"}}}}'`)
- Optionally `baseHash` — from a prior `config.get` snapshot (tool fetches if omitted)

**Guidance for agents:** Add to AGENTS.md or SOUL.md: *"When using gateway config.patch, always pass `raw` as a JSON string of the partial config to merge."*

---

## "Gateway restart is disabled" (restart)

**Cause:** OpenClaw's `commands.restart` is `false` by default (security). The agent tried to restart the gateway but it's not allowed.

**Fix (if you want the agent to restart the gateway):** Add to `data/openclaw/openclaw.json`:

```json
"commands": {
  "restart": true
}
```

**Security note:** Enabling this lets the agent restart the OpenClaw gateway. Use only if you trust the agent and understand the implications. Restart is often disabled to prevent accidental or malicious restarts.

---

## "Device token mismatch" (browser)

**Cause:** The browser tool uses a device token for the connection. If the token was rotated, expired, or the browser session was recreated, the client and server tokens no longer match.

**Fix:** Typically requires re-pairing the browser or re-running the browser setup. See [OpenClaw browser docs](https://docs.openclaw.ai/tools/browser) and the "device token mismatch" section in [OpenClaw gateway error guides](https://clawtank.dev/blog/openclaw-gateway-errors-complete-guide).
