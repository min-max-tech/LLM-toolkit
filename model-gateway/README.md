# Model Gateway

OpenAI-compatible proxy for unified model access. Routes chat and embedding requests to Ollama (and future providers like vLLM).

**Status:** See [docs/ARCHITECTURE_RFC.md](../docs/ARCHITECTURE_RFC.md) for design and implementation plan.

## Endpoints

- `GET /v1/models` — List models from all providers
- `POST /v1/chat/completions` — Chat completion (streaming supported)
- `POST /v1/embeddings` — Embeddings
- `GET /health` — Gateway health

## Config

| Variable | Description |
|----------|-------------|
| `OLLAMA_URL` | Upstream Ollama URL (default: `http://ollama:11434`) |
| `OPENAI_COMPAT_PORT` | Port to listen on (default: `11435`) |
