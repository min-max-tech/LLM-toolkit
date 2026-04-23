# Configuration Quick Reference

Short reference for the env vars, MCP config, and compute overrides you'll touch most often. `.env.example` is the canonical list; this page highlights the common ones and how they interact.

## Environment Variables

Copy `.env.example` to `.env` and set at least `BASE_PATH`. Everything else has sensible defaults.

### Required

| Variable | Default | Purpose |
|---|---|---|
| `BASE_PATH` | `.` | Repository root (forward slashes on Windows, e.g. `C:/dev/AI-toolkit`) |

### Commonly set

| Variable | Default | Purpose |
|---|---|---|
| `DATA_PATH` | `${BASE_PATH}/data` | Override data directory location |
| `DEFAULT_MODEL` | `local-chat` | Canonical model alias used by Open WebUI, Hermes, and LiteLLM |
| `MODELS` | *(see `.env.example`)* | Comma-separated Ollama models to pull on first start |
| `OPS_CONTROLLER_TOKEN` | *(empty)* | Required for dashboard-driven service lifecycle (`openssl rand -hex 32`) |
| `DASHBOARD_AUTH_TOKEN` | *(empty)* | Optional Bearer auth on dashboard `/api/*` |
| `HF_TOKEN` | *(empty)* | Hugging Face token for gated model downloads |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | *(empty)* | GitHub MCP server token; also passed to `comfyui` as `GITHUB_TOKEN` for Manager API |
| `TAVILY_API_KEY` | *(empty)* | Required if the `tavily` MCP server is enabled |
| `COMPUTE_MODE` | *(auto-detected)* | Override GPU type: `nvidia`, `amd`, `intel`, `cpu` |

### Hermes Agent

See [hermes-agent.md](hermes-agent.md) for the full setup flow.

| Variable | Default | Purpose |
|---|---|---|
| `HERMES_DASHBOARD_PORT` | `9119` | Host port for the Hermes dashboard |
| `DISCORD_BOT_TOKEN` | *(empty)* | Discord bot token. Legacy `DISCORD_TOKEN` is aliased automatically. |
| `DISCORD_ALLOWED_USERS` | *(empty)* | Comma-separated Discord user IDs authorized to DM / invoke the bot. Required for Discord use. |
| `DISCORD_ALLOWED_CHANNELS` | *(empty)* | Comma-separated channel IDs where the bot may respond. Optional. |
| `DISCORD_REQUIRE_MENTION` | `true` | Require `@bot` mention to respond. |

### RAG (`--profile rag`)

| Variable | Default | Purpose |
|---|---|---|
| `EMBED_MODEL` | `nomic-embed-text-v1.5.Q4_K_M.gguf` | Embedding model used by `rag-ingestion` and Open WebUI |
| `RAG_COLLECTION` | `documents` | Qdrant collection (must match Open WebUI / ingestion) |
| `RAG_CHUNK_SIZE` | `400` | Chunk size in tokens |
| `RAG_CHUNK_OVERLAP` | `50` | Chunk overlap in tokens |
| `QDRANT_PORT` | `6333` | Qdrant host port (change if something else already uses 6333) |

## MCP Server Configuration

Repo templates live under `mcp/gateway/`; runtime files are in `data/mcp/` (bind-mounted into the gateway). See [mcp/README.md](../mcp/README.md).

Enabled servers are listed in `data/mcp/servers.txt` (one per line). Metadata, per-server `allow_clients`, and rate limits live in `data/mcp/registry.json`.

Default servers: `duckduckgo`, `n8n`, `tavily`, `comfyui` (Tavily requires `TAVILY_API_KEY`). Override with `MCP_GATEWAY_SERVERS` in `.env`:

```
MCP_GATEWAY_SERVERS=duckduckgo,github-official
```

Edits to `servers.txt` trigger a gateway reload within ~10 seconds — no container restart needed.

## Compute Configuration

`scripts/detect_hardware.py` runs via the `compose` wrapper and writes `overrides/compute.yml` (gitignored). It's re-detected every time you invoke `./compose`.

To override manually, set `COMPUTE_MODE` and `COMPOSE_FILE` in `.env`:

```
COMPUTE_MODE=nvidia
COMPOSE_FILE=docker-compose.yml;overrides/compute.yml
```

**ComfyUI `CLI_ARGS`:** Set `COMFYUI_CLI_ARGS` in `.env`, or accept the default that `detect_hardware.py` supplies (GPU stacks get `--normalvram` so text encoders stay on GPU). Without the var, the compose base default is `--cpu --enable-manager`.

## Data Persistence Rules

All `data/` and `models/` directories are bind-mounted and persist across container restarts.

| Directory | Purpose |
|---|---|
| `data/hermes/` | Hermes agent runtime state (sessions, per-user allowlists) |
| `data/qdrant/` | Qdrant vector DB storage |
| `data/rag-input/` | Drop files here for `rag-ingestion` |
| `data/ops-controller/` | Audit logs |
| `data/mcp/` | `servers.txt`, `registry.json`, `registry-custom.yaml` |
| `data/dashboard/` | Dashboard throughput / benchmark data |
| `data/comfyui-storage/` | ComfyUI outputs, custom nodes, local configs |
| `models/ollama/` | Ollama model blobs |
| `models/gguf/` | llama.cpp GGUF files |
| `models/comfyui/` | ComfyUI checkpoints, LoRAs, VAEs, encoders |

`/tmp` inside containers is tmpfs; nothing there survives a restart.

## Network Ports

| Service | Host port | Description |
|---|---|---|
| Dashboard | `8080` | Dashboard API + control center |
| Open WebUI | `3000` | Chat interface |
| Model Gateway | `11435` | OpenAI-compatible model endpoint (LiteLLM in front of llama.cpp) |
| ComfyUI | `8188` | Image / audio / video generation |
| n8n | `5678` | Workflow automation |
| Hermes dashboard | `9119` | Overridable via `HERMES_DASHBOARD_PORT` |
| MCP Gateway | `8811` | Published on host so external clients (Cursor, Claude Desktop) can reach it |
| Ollama | `11434` | **Backend-only by default.** Expose via `overrides/ollama-expose.yml` |
| Qdrant | `6333` | RAG profile only |
| Ops Controller | internal `9000` | Not published on the host |

## Audit Log Schema

`data/ops-controller/audit.log` is JSONL, append-only, one event per line:

```json
{"timestamp":"2026-03-22T10:00:00Z","action":"model_pulled","model":"qwen3:8b","status":"success"}
{"timestamp":"2026-03-22T10:01:00Z","action":"service_started","service":"ollama","status":"success"}
```

## Minimal `.env`

```
BASE_PATH=.

# Models
MODELS=qwen3:8b,deepseek-r1:7b,nomic-embed-text
DEFAULT_MODEL=local-chat

# Ops
OPS_CONTROLLER_TOKEN=ops-controller-token-here
DASHBOARD_AUTH_TOKEN=dashboard-token-here

# Optional
HF_TOKEN=
GITHUB_PERSONAL_ACCESS_TOKEN=

# RAG
EMBED_MODEL=nomic-embed-text-v1.5.Q4_K_M.gguf
```
