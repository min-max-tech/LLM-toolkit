# LLM-toolkit

Hey, I am Cam, I made this repo to simplify my local-LLM setup. I wanted a bunch of tools setup in a single spot -- and of course, all dockerized. 

Ollama + Open WebUI + ComfyUI + N8N in Docker. One command, all on one drive.

→ [Repository structure](docs/STRUCTURE.md)

## Services

| Service | Port | Purpose |
|---------|------|---------|
| **dashboard** | 8080 | **Unified model manager** — [localhost:8080](http://localhost:8080) |
| **ollama** | 11434 | Local LLM runtime (GPU) |
| **open-webui** | 3000 | Chat UI — [localhost:3000](http://localhost:3000) |
| **comfyui** | 8188 | Stable Diffusion / LTX-2 — [localhost:8188](http://localhost:8188) |
| **n8n** | 5678 | Workflow automation — [localhost:5678](http://localhost:5678) |
| **OpenClaw** | 18789 | Personal AI assistant — [openclaw/](openclaw/) |
| model-puller | — | Ready to pull Ollama models on demand |
| comfyui-model-puller | — | Ready to download LTX-2 models (~60 GB) on demand |

## Quick start

```powershell
# 1. Clone / copy to your target drive (repo name: LLM-toolkit)
cd F:\LLM-toolkit

# 2. Create .env (edit BASE_PATH to match your install path)
copy .env.example .env

# 3. Create data directories and openclaw/.env (required for OpenClaw)
.\scripts\ensure_dirs.ps1

# 4. Start all services
docker compose up -d
```

All services start by default. Open the **dashboard** at [localhost:8080](http://localhost:8080) to manage models and see service status.

**If ComfyUI or OpenClaw fail:** The dashboard shows troubleshooting hints. ComfyUI requires an NVIDIA GPU; OpenClaw needs `openclaw/.env` (created by step 3).

**On-demand commands** (run when you want to pull models):
- `docker compose run --rm model-puller` — pull Ollama models from `.env`
- `docker compose run --rm comfyui-model-puller` — download LTX-2 models (~60 GB)
- `docker compose run --rm openclaw-cli onboard` — OpenClaw setup

## Dashboard

The **dashboard** at [localhost:8080](http://localhost:8080) gives you a single web UI to:

- **View all models** — Ollama (LLM) and ComfyUI (LTX-2) in one place
- **Pull models** — searchable dropdown with 150+ Ollama models; or type any model name
- **Jump to services** — Open WebUI, ComfyUI, N8N, OpenClaw

**Not seeing updates?** After pulling code changes, rebuild: `docker compose build dashboard && docker compose up -d`

## Ollama models

Default models (set in `.env`):

- `deepseek-r1:7b` — reasoning
- `deepseek-coder:6.7b` — coding
- `nomic-embed-text` — embeddings / RAG

**Pull via dashboard** (recommended) or via CLI:

```bash
docker compose run --rm model-puller   # on-demand from .env
# Or use the dashboard at localhost:8080
```

## ComfyUI (LTX-2)

ComfyUI starts independently. LTX-2 models (~60 GB) are downloaded on demand — first run takes a while; subsequent runs skip existing files.

**Includes:** LTX-2 checkpoint (fp8), LoRAs, latent upscaler, Gemma 3 12B text encoder.

**Pull via dashboard** (recommended) or:

```bash
docker compose run --rm comfyui-model-puller
```

## Security

- **Open WebUI** runs with `WEBUI_AUTH=False` by default (no login). Suitable for local/single-user use. If exposing to a network, set `WEBUI_AUTH=True` in the environment.
- **OpenClaw** requires a gateway token — generate with `openssl rand -hex 32`.
- Never commit `.env` or `openclaw/.env`. See [SECURITY.md](SECURITY.md) for details.

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
| `models/comfyui/` | LTX-2 models (downloaded on demand) |

## OpenClaw

[OpenClaw](openclaw/) is a personal AI assistant, integrated in the main compose. See [openclaw/README.md](openclaw/README.md) for token setup.

## Commands

```powershell
docker compose up -d      # Start all services
docker compose logs -f ollama
docker compose down       # Stop
```
