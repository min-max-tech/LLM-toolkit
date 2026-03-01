# Troubleshooting Runbook

## Quick Diagnostics

```bash
# Service status
docker compose ps

# Recent logs
docker compose logs --tail=50

# Health checks
curl -s http://localhost:8080/api/health | jq
curl -s http://localhost:11435/health | jq
curl -s http://localhost:8811/mcp
```

## Common Issues

### Dashboard unreachable (8080)

- **Check**: `docker compose logs dashboard`
- **Causes**: Port conflict, container crash, auth misconfiguration
- **Fix**: Ensure port 8080 is free; check `DASHBOARD_AUTH_TOKEN` / `DASHBOARD_PASSWORD` if set

### Ollama container unhealthy / failed to start

- **Cause:** The official Ollama image has no `curl` or `wget`. A healthcheck that uses `curl` will always fail.
- **Fix:** Use a healthcheck that runs `ollama list` (see docker-compose.yml). If you use a custom image, ensure the healthcheck command exists in the container.

### Model Gateway 502 / Ollama connection refused

- **Check**: `docker compose logs model-gateway` and `docker compose logs ollama`
- **Causes**: Ollama not ready, wrong `OLLAMA_URL`
- **Fix**: Wait for Ollama healthcheck; ensure `OLLAMA_URL=http://ollama:11434` in model-gateway env

### MCP Gateway / tools not loading

- **Check**: `data/mcp/servers.txt` exists and has entries; `docker compose logs mcp-gateway`
- **Causes**: Empty servers.txt, registry.json parse error, Docker socket permission
- **Fix**: Add servers via dashboard or `echo "duckduckgo" >> data/mcp/servers.txt`; ensure `registry.json` is valid JSON if present

### MCP filesystem: "ENOENT no such file or directory, stat ''"

- **Cause:** The `filesystem` MCP server expects a root directory to be configured. When the gateway starts it without a path (default), it tries to stat an empty path and fails.
- **Fix:** Either remove `filesystem` from `data/mcp/servers.txt` if you don't need file access (e.g. use `duckduckgo,hugging-face` only), or configure the filesystem server with a root directory via the Docker MCP Gateway / registry if your gateway version supports per-server env or volume mounts. Other tools (duckduckgo, hugging-face) will still work.

### Open WebUI can't reach models

- **Check**: `OPENAI_API_BASE` or `OLLAMA_BASE_URL` in open-webui env
- **Fix**: Point to model gateway: `OPENAI_API_BASE=http://model-gateway:11435/v1` or use `OLLAMA_BASE_URL=http://ollama:11434`

### Ops controller / Start-Stop not working

- **Check**: `OPS_CONTROLLER_TOKEN` set in dashboard and ops-controller; `docker compose logs ops-controller`
- **Causes**: Token mismatch, Docker socket not mounted
- **Fix**: Set same token in both; ensure `/var/run/docker.sock` is mounted in ops-controller

### ComfyUI / N8N out of memory

- **Check**: `docker stats`
- **Fix**: Increase `deploy.resources.limits.memory` in docker-compose.yml or add swap

### vLLM not appearing in model list

- **Check**: `VLLM_URL` set in model-gateway env; vLLM service running and healthy
- **Fix**: Add vLLM service to compose if needed; set `VLLM_URL=http://vllm:8000`

### n8n: "Permissions 0777 ... too wide" / "EPERM: operation not permitted"

- **Cause:** n8n tries to tighten permissions on its config file; in some volume setups (e.g. bind mount) the container cannot change ownership/permissions.
- **Fix:** Usually safe to ignore; n8n still runs. To silence the check, set `N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false` in the n8n service environment in docker-compose.

### n8n: "Failed to start Python task runner ... Python 3 is missing"

- **Cause:** n8n's internal Python task runner is for debugging; production expects an external Python runner.
- **Fix:** No action required. Use the JS Task Runner for workflows; for Python nodes, see [n8n external task runner docs](https://docs.n8n.io/hosting/configuration/task-runners/#setting-up-external-mode).

## OpenClaw gateway tool

### "Missing raw parameter" (config.patch)

**Cause:** The gateway tool's `config.patch` action requires a `raw` parameter — a JSON string of the partial config to merge. The agent invoked config.patch without supplying it.

**Fix:** When using `gateway` with `action: "config.patch"`, the agent must pass:
- `raw` — JSON string of the config fragment to merge (e.g. `'{"agents":{"defaults":{"model":{"primary":"gateway/ollama/deepseek-r1:7b"}}}}'`)
- Optionally `baseHash` — from a prior `config.get` snapshot (tool fetches if omitted)

**Guidance for agents:** Add to AGENTS.md or SOUL.md: *"When using gateway config.patch, always pass `raw` as a JSON string of the partial config to merge."*

### "Gateway restart is disabled" (restart)

**Cause:** OpenClaw's `commands.restart` is `false` by default (security). The agent tried to restart the gateway but it's not allowed.

**Fix (if you want the agent to restart the gateway):** Add to `data/openclaw/openclaw.json`:

```json
"commands": {
  "restart": true
}
```

**Security note:** Enabling this lets the agent restart the OpenClaw gateway. Use only if you trust the agent and understand the implications.

### "Device token mismatch" (browser or agent backend)

**Cause:** A client (browser or agent backend) has a stored device token that no longer matches the gateway — e.g. after a gateway/container restart, config change, or container rebuild.

**Fix (manual re-pair / reissue):** You do **not** need to run full `docker compose up` again. Restarting only the OpenClaw Gateway container is enough after fixing tokens. Follow these steps:

1. **Run the built-in fix** (same config volume as the gateway):
   ```powershell
   docker compose --profile openclaw-cli run --rm openclaw-cli doctor --fix
   ```
   This detects token mismatches and regenerates matching tokens in `data/openclaw`.

2. **Restart only the gateway** so it loads the updated tokens:
   ```powershell
   docker compose restart openclaw-gateway
   ```
   Wait until logs show the gateway is listening (e.g. `docker compose logs -f openclaw-gateway`).

3. **Re-pair clients** as needed:
   - **Browser:** Open the gateway URL (e.g. http://localhost:18789) in a private/incognito window or clear site data for that URL, then reconnect and paste the gateway token from `openclaw/.env` (`OPENCLAW_GATEWAY_TOKEN`). Approve the device if prompted.
   - **Agent backend:** Reconnect from the agent (e.g. Cursor / OpenClaw integration); if it shows a new device/pairing request, approve it (see step 4).

4. **Optional — list/approve/remove devices:**  
   When running the CLI via Docker, the CLI uses local discovery and hits the wrong host. Use the helper script (from repo root), which passes `--url ws://openclaw-gateway:18789` and `--token` from `openclaw/.env`:
   ```powershell
   .\openclaw\scripts\run-cli.ps1 devices list
   # Approve a pending device (replace DEVICE_ID with the actual id from the list):
   .\openclaw\scripts\run-cli.ps1 devices approve DEVICE_ID
   # Or remove a stuck device so it can re-pair:
   .\openclaw\scripts\run-cli.ps1 devices remove DEVICE_ID
   ```
   If you see `gateway closed (1006)` or "Gateway target: ws://172.18.0.x", you are not using the script (or the script failed to read the token). Use `run-cli.ps1` so the CLI targets the gateway container.

**Prevention:** Pin the gateway token so it does not change on restart: set `OPENCLAW_GATEWAY_TOKEN` in `openclaw/.env` and keep it unchanged. See [ClawTank: device token mismatch](https://clawtank.dev/blog/openclaw-device-token-mismatch-fix).

## Log Locations

| Service        | Logs                    |
|----------------|-------------------------|
| Dashboard      | `docker compose logs dashboard` |
| Model Gateway  | `docker compose logs model-gateway` |
| MCP Gateway    | `docker compose logs mcp-gateway` |
| Ops Controller | `docker compose logs ops-controller` |
| Audit          | `data/ops-controller/audit.log` |

### OpenClaw: "Invalid config ... Unrecognized key: mcp"

- **Cause:** Some OpenClaw versions do not support a top-level `mcp` key in `openclaw.json`. Adding it can make the gateway reject the config and fail WebSocket connections (code 4008).
- **Fix:** Remove the `mcp` block from `data/openclaw/openclaw.json` if present. Configure MCP via OpenClaw’s UI or the version’s documented config (e.g. under agents or a different path). See [openclaw/README.md](../../openclaw/README.md).

## Escalation

- **Security**: See [SECURITY.md](../../SECURITY.md) (pre-deploy checklist, break-glass)
- **Architecture**: See [docs/ARCHITECTURE_RFC.md](../ARCHITECTURE_RFC.md)
- **OpenClaw**: See [openclaw/README.md](../../openclaw/README.md)
