# Repository State

Snapshot of the AI-toolkit repo for context and onboarding. See [docs/ARCHITECTURE_RFC.md](docs/ARCHITECTURE_RFC.md) for full architecture and milestones.

**Last updated:** 2026-03-01

---

## Services (Docker Compose)

| Service | Port (host) | Role | Networks |
|--------|-------------|------|----------|
| ollama | 11434 | LLM inference (Ollama API) | backend |
| model-gateway | 11435 | OpenAI-compatible proxy (Ollama + vLLM) | frontend, backend |
| ops-controller | — (internal) | Start/stop/restart/logs/audit; docker.sock | backend |
| dashboard | 8080 | Model/MCP/ops UI; no docker.sock | frontend, backend |
| open-webui | 3000 | Chat UI (defaults to model gateway) | frontend |
| mcp-gateway | 8811 | MCP tool gateway (servers.txt + registry.json) | frontend |
| n8n | 5678 | Workflow automation | frontend |
| comfyui | 8188 | Image generation | frontend |
| openclaw-gateway | 18789, 18790 | Agent runtime (models + MCP bridge) | frontend, backend |
| vllm | — (optional) | vLLM server; profile `vllm` | backend |

**Networks:** `ai-toolkit-frontend`, `ai-toolkit-backend`. Backend-only: ollama, ops-controller. Both: model-gateway, dashboard, openclaw-gateway.

**Profiles:** `models` (model-puller), `comfyui-models`, `openclaw-cli`, `vllm` (docker-compose.vllm.yml).

---

## Key Paths

| Path | Purpose |
|------|---------|
| `data/mcp/servers.txt` | Enabled MCP servers (comma-separated); hot-reload |
| `data/mcp/registry.json` | MCP server metadata (scopes, allow_clients, env_schema) |
| `data/ops-controller/audit.log` | JSONL audit log (privileged actions) |
| `data/openclaw/` | OpenClaw config and workspace (gitignored) |
| `.env` | Secrets and overrides (gitignored); copy from .env.example |

---

## Tests

- **Contract:** `tests/test_model_gateway_contract.py`, `test_model_gateway_cache.py`, `test_ops_controller_audit.py`, `test_dashboard_health.py`
- **Compose:** `tests/test_compose_smoke.py` — config validation; set `RUN_COMPOSE_SMOKE=1` for runtime smoke (Docker required)

Run: `python -m pytest tests/ -v`

---

## Docs

| Doc | Purpose |
|-----|---------|
| [docs/ARCHITECTURE_RFC.md](docs/ARCHITECTURE_RFC.md) | Target architecture, workstreams, milestones, security |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | Workflows, Tailscale, optional vLLM |
| [docs/audit/SCHEMA.md](docs/audit/SCHEMA.md) | Audit event schema |
| [docs/runbooks/TROUBLESHOOTING.md](docs/runbooks/TROUBLESHOOTING.md) | Common issues and fixes |
| [docs/runbooks/SECURITY_HARDENING.md](docs/runbooks/SECURITY_HARDENING.md) | SSRF egress, token rotation, hardening checks |
| [SECURITY.md](SECURITY.md) | Pre-deploy checklist, break-glass |
| [mcp/README.md](mcp/README.md) | MCP gateway usage and OpenClaw plugin |
| [openclaw/README.md](openclaw/README.md) | OpenClaw config and gateway |

---

## Milestones (from RFC)

| M | Status | Summary |
|---|--------|---------|
| M0 | ✅ | Audit schema, healthchecks, log rotation, SECURITY.md |
| M1 | ✅ | Model Gateway (OpenAI-compat, Ollama + vLLM) |
| M2 | ✅ | Ops Controller + dashboard integration |
| M3 | ✅ | MCP registry, cap_drop/read_only, model cache, Open WebUI default |
| M4 | ✅ | Networks, X-Request-ID → audit, vLLM profile, smoke tests |
| M5 | 🔲 | Dashboard MCP health badges in UI; optional SSRF script; policy tests |

---

## Single-command bring-up

```bash
docker compose up -d
# Optional: pull models first
docker compose --profile models up -d model-puller
# Optional: vLLM
docker compose -f docker-compose.yml -f docker-compose.vllm.yml --profile vllm up -d
# Then set VLLM_URL=http://vllm:8000 and restart model-gateway
```
