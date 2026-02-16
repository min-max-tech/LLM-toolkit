# Local LLM Stack (Docker)

Run Ollama + Open WebUI in Docker with optional one-shot model pulling.

## What's included

| Service       | Purpose |
|---------------|--------|
| **ollama**    | Local LLM runtime. Exposed on `11434` (optional; can be used only from Open WebUI). |
| **open-webui**| Web UI at [http://localhost:3000](http://localhost:3000). |
| **model-puller** | Runs once on first `up` to pull the models listed in `MODELS` (or `.env`). |
| **comfyui-model-puller** | Runs once on first `up` to download LTX-2 models (~60GB) to `./models/comfyui/`. |
| **comfyui**   | Stable Diffusion node-based UI at [http://localhost:8188](http://localhost:8188). Waits for model puller. Requires NVIDIA GPU. |
| **n8n**       | Workflow automation at [http://localhost:5678](http://localhost:5678). |

## Quick start

1. **Copy the project to your target drive** (e.g. D: to save C: space)
   ```powershell
   # Copy to D: (or E:, etc.)
   xcopy /E /I "c:\Users\lynch\local-llm-docker" "D:\local-llm-docker"
   cd D:\local-llm-docker
   ```

2. **Configure `.env`**
   - Copy `.env.example` to `.env`
   - Set `BASE_PATH=D:/local-llm-docker` (or your project path). **All data lives under this path** – no Docker volumes on C:.

3. **Optional: set models to pull**
   - Edit `MODELS` in `docker-compose.yml` under `model-puller`, or
   - Copy `.env.example` to `.env` and set `MODELS=model1:tag,model2:tag`

4. **Create data directories** (first run only)
   ```powershell
   cd D:\local-llm-docker
   $env:BASE_PATH = "D:/local-llm-docker"
   .\scripts\ensure_dirs.ps1
   ```

5. **Start the stack**
   ```bash
   docker compose up -d
   ```

6. Open **http://localhost:3000** and sign up / log in. Models will appear as they finish pulling (watch logs with `docker compose logs -f model-puller`).

## Customizing models

Default models in the compose file:

- `deepseek-r1:7b` – reasoning
- `deepseek-coder:6.7b` – coding
- `nomic-embed-text` – embeddings (e.g. for RAG)

Change them by editing the `MODELS` environment variable for `model-puller` in `docker-compose.yml`, or in a `.env` file:

```env
MODELS=llama3.2:3b,mistral:7b,nomic-embed-text
```

Comma-separated, no spaces (or they’ll be trimmed). After changing, run:

```bash
docker compose up -d model-puller
```

to pull the new list (existing models are skipped).

## ComfyUI (LTX-2)

ComfyUI starts after `comfyui-model-puller` has downloaded the LTX-2 models (~60GB total). First run may take a while; subsequent runs skip existing files.

**Auto-downloaded:** checkpoint (fp8), LoRAs, latent upscaler, Gemma text encoder (~24GB).

To re-pull models:

```bash
docker compose up -d comfyui-model-puller
```

## GPU (NVIDIA)

If you use the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html), uncomment the GPU block under the `ollama` service in `docker-compose.yml`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

Or, with Compose v2 and a recent Docker engine, you can use:

```yaml
gpus: all
```

Then restart:

```bash
docker compose up -d ollama
```

## Ports and access

- **3000** – Open WebUI (browser).
- **5678** – N8N (workflow automation).
- **8188** – ComfyUI (Stable Diffusion).
- **11434** – Ollama API (for CLI, scripts, or other apps). You can remove the `ports` mapping for `ollama` if you only want access through Open WebUI.

## Data (all under BASE_PATH, e.g. D:/local-llm-docker)

| Path | Contents |
|------|----------|
| `data/ollama` | Ollama models and data |
| `data/open-webui` | Open WebUI users, chats, settings |
| `data/comfyui-output` | ComfyUI generated images |
| `data/n8n-data` | N8N workflows |
| `data/n8n-files` | N8N shared files |
| `models/comfyui/` | LTX-2 models (checkpoints, loras, upscalers, Gemma). Auto-downloaded on first run |

Everything is on disk via bind mounts – no Docker named volumes. Back up the `data/` and `models/` dirs if you care about state.

**Migrating from named volumes:** If you previously used the default setup (Docker volumes on C:), run `docker compose down` first. The new bind mounts start empty. To migrate Ollama models, copy from the old volume (use `docker run --rm -v ollama:/from -v D:/local-llm-docker/data/ollama:/to alpine cp -a /from/. /to/` – adjust paths). Otherwise start fresh.

## Commands

```bash
# Start everything
docker compose up -d

# View logs (e.g. model pull progress)
docker compose logs -f model-puller
docker compose logs -f comfyui-model-puller
docker compose logs -f ollama

# Stop
docker compose down

# Stop and remove volumes (deletes models and UI data)
docker compose down -v
```

## License

Use and modify as you like. Ollama and Open WebUI have their own licenses.
