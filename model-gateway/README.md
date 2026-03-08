# Model Gateway

OpenAI-compatible proxy for unified model access. Routes chat and embedding requests to Ollama (and future providers like vLLM).

**Status:** See [Product Requirements Document](../docs/Product%20Requirements%20Document.md) for design and decisions.

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
