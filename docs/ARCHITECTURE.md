# AI-toolkit Architecture

Short overview. Full design: [ARCHITECTURE_RFC.md](ARCHITECTURE_RFC.md).

## Target Architecture

```
User → Dashboard / Open WebUI / N8N / OpenClaw
         │
         ├── Model Gateway (:11435) → Ollama / vLLM
         ├── MCP Gateway (:8811) → shared tools
         └── Ops Controller (:9000) → Docker Compose lifecycle
```

## Components

| Component | Purpose |
|-----------|---------|
| **Model Gateway** | OpenAI-compatible proxy; single endpoint for chat/embeddings |
| **MCP Gateway** | Shared MCP tools; registry + policy (allowlist, health) |
| **Ops Controller** | Authenticated API for start/stop/restart, logs, audit |
| **Dashboard** | UI for models, MCP, services; calls controller for ops |

## Principles

- **Local-first** — single command bring-up
- **Least privilege** — dashboard never mounts docker.sock
- **One model endpoint** — OpenAI-compatible surface
- **Safe ops** — controller requires token; audit log
