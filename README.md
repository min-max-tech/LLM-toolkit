# Local LLM Stack (Docker)

Ollama + Open WebUI + ComfyUI + N8N in Docker. One command, all on one drive.

→ [Repository structure](docs/STRUCTURE.md)

## Services

| Service | Port | Purpose |
|---------|------|---------|
| **ollama** | 11434 | Local LLM runtime (GPU) |
| **open-webui** | 3000 | Chat UI — [localhost:3000](http://localhost:3000) |
| **comfyui** | 8188 | Stable Diffusion / LTX-2 — [localhost:8188](http://localhost:8188) |
| **n8n** | 5678 | Workflow automation — [localhost:5678](http://localhost:5678) |
| **OpenClaw** | 18789 | Personal AI assistant — [openclaw/](openclaw/) |
| model-puller | — | Pulls Ollama models once on first start |
| comfyui-model-puller | — | Downloads LTX-2 models (~60 GB) once on first start |

## Quick start

```powershell
# 1. Clone / copy to your target drive
cd F:\local-llm-docker

# 2. Create .env (edit BASE_PATH if needed)
copy .env.example .env

# 3. Create data directories
.\scripts\ensure_dirs.ps1

# 4. Start
docker compose up -d
```

Open **http://localhost:3000** to use the chat UI.

## Ollama models

Default models (set in `.env`):

- `deepseek-r1:7b` — reasoning
- `deepseek-coder:6.7b` — coding
- `nomic-embed-text` — embeddings / RAG

Change them in `.env` and re-pull:

```bash
docker compose up -d model-puller
```

## ComfyUI (LTX-2)

ComfyUI waits for `comfyui-model-puller` to finish downloading LTX-2 models (~60 GB). First run takes a while; subsequent runs skip existing files.

**Auto-downloaded:** LTX-2 checkpoint (fp8), LoRAs, latent upscaler, Gemma 3 12B text encoder.

Re-pull models:

```bash
docker compose up -d comfyui-model-puller
```

## GPU

The `ollama` and `comfyui` services are configured for NVIDIA GPU via the Container Toolkit. Remove the `deploy` block if you don't have a GPU.

## Data

All data is stored under `BASE_PATH` via bind mounts — no Docker named volumes.

| Path | Contents |
|------|----------|
| `data/ollama` | Ollama models |
| `data/open-webui` | Users, chats, settings |
| `data/comfyui-output` | Generated images/video |
| `data/n8n-data` | Workflows |
| `data/n8n-files` | Shared files |
| `data/openclaw` | OpenClaw config + workspace (SOUL.md, AGENTS.md, TOOLS.md) |
| `models/comfyui/` | LTX-2 models (auto-downloaded) |

## OpenClaw (optional)

[OpenClaw](openclaw/) is a personal AI assistant in a separate compose file. See [openclaw/README.md](openclaw/README.md) for setup.

```bash
cd openclaw && docker compose up -d openclaw-gateway
```

## Commands

```bash
docker compose up -d              # Start everything
docker compose logs -f ollama     # View logs
docker compose down               # Stop
docker compose down -v            # Stop + remove volumes
```
