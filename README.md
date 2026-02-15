# Local LLM Stack (Docker)

Run Ollama + Open WebUI in Docker with optional one-shot model pulling.

## What's included

| Service       | Purpose |
|---------------|--------|
| **ollama**    | Local LLM runtime. Exposed on `11434` (optional; can be used only from Open WebUI). |
| **open-webui**| Web UI at [http://localhost:3000](http://localhost:3000). |
| **model-puller** | Runs once on first `up` to pull the models listed in `MODELS` (or `.env`). |
| **comfyui**   | Stable Diffusion node-based UI at [http://localhost:8188](http://localhost:8188). Requires NVIDIA GPU. |
| **n8n**       | Workflow automation at [http://localhost:5678](http://localhost:5678). |

## Quick start

1. **Clone and enter the repo**
   ```bash
   cd local-llm-docker
   ```

2. **Optional: set models to pull**
   - Edit `MODELS` in `docker-compose.yml` under `model-puller`, or
   - Copy `.env.example` to `.env` and set `MODELS=model1:tag,model2:tag`

3. **Start the stack**
   ```bash
   docker compose up -d
   ```

4. Open **http://localhost:3000** and sign up / log in. Models will appear as they finish pulling (watch logs with `docker compose logs -f model-puller`).

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

## Data

- `ollama` volume: model files and Ollama data.
- `open-webui` volume: Open WebUI data (users, chats, settings).
- `comfyui-models`, `comfyui-custom-nodes`, `comfyui-output`: ComfyUI models, extensions, and generated images.
- `n8n-data`, `n8n-files`: N8N workflows and shared files (use `/files` in N8N for file nodes).

Back up these volumes if you care about models and UI state.

## Commands

```bash
# Start everything
docker compose up -d

# View logs (e.g. model pull progress)
docker compose logs -f model-puller
docker compose logs -f ollama

# Stop
docker compose down

# Stop and remove volumes (deletes models and UI data)
docker compose down -v
```

## License

Use and modify as you like. Ollama and Open WebUI have their own licenses.
