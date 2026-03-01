# OpenClaw → Dashboard Performance Audit

## Flow

```
User chats (Discord/UI) → OpenClaw Gateway → [Provider] → Model
                                                    ↓
                                         If gateway: Model Gateway → Ollama
                                                    ↓
                                         Model Gateway records → Dashboard /api/throughput/record
```

**Critical:** Throughput is only recorded when requests go through the **Model Gateway**. Direct Ollama traffic is not monitored.

## Root Cause: Provider Selection

OpenClaw supports multiple providers. The selected provider determines where requests go:

| Provider | baseUrl | API | Traffic path | Dashboard sees it? |
|----------|---------|-----|--------------|--------------------|
| **ollama** | http://ollama:11434 | native | OpenClaw → Ollama | **No** |
| **gateway** | http://model-gateway:11435/v1 | openai | OpenClaw → Model Gateway → Ollama | **Yes** |

If the user selects a model from the **ollama** provider, traffic bypasses the Model Gateway and never reaches the dashboard.

## Checklist

### 1. openclaw.json must have the gateway provider

Location: `data/openclaw/openclaw.json`

```json
"models": {
  "providers": {
    "gateway": {
      "baseUrl": "http://model-gateway:11435/v1",
      "apiKey": "ollama-local",
      "api": "openai"
    },
    "ollama": { ... }
  }
}
```

**Problem:** Existing users may have config created before the gateway was added. `ensure_dirs` only copies the example when the file doesn't exist.

### 2. User must select a gateway model

In OpenClaw UI: Settings → Model → pick a model from the **gateway** provider.

Models from the gateway appear with a prefix (e.g. `gateway/ollama/deepseek-r1:7b` or similar, depending on OpenClaw version). If the user only sees `ollama/` models, they're using the ollama provider.

### 3. OLLAMA_BASE_URL env (docker-compose)

```yaml
OLLAMA_BASE_URL: "http://ollama:11434"
```

This may override the ollama provider's baseUrl. It does **not** affect the gateway provider. The gateway provider uses its own baseUrl from the config.

### 4. Model Gateway

- `DASHBOARD_URL=http://dashboard:8080` ✓ (set in docker-compose)
- Records throughput for both streaming and non-streaming chat ✓
- OpenClaw calls are server-to-server → no Origin header → service shows as "unknown" (throughput still recorded)

### 5. Network

OpenClaw gateway and Model Gateway are on the same Docker network. `model-gateway:11435` is reachable from `openclaw-gateway`.

## Fix: Config Sync (implemented)

`openclaw-config-sync` runs before `openclaw-gateway` on `docker compose up`:

1. **Missing gateway provider** → Adds it from the template.
2. **Existing gateway without X-Service-Name** → Adds `headers: {"X-Service-Name": "openclaw"}` so the dashboard shows "openclaw" in Service usage.

**User action still required:** In OpenClaw Settings → Model, select a model from the **gateway** provider (e.g. `gateway/ollama/deepseek-r1:7b`). If you only see `ollama/` models, the gateway provider is now in your config—refresh the model list or restart OpenClaw.
