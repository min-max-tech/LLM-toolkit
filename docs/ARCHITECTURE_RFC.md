# AI Platform-in-a-Box — Architecture RFC

**Status:** Draft  
**Date:** 2025-02-28  
**Scope:** Transform LLM-toolkit into a cohesive local-first AI platform with unified model access, shared tools, and dashboard-driven operations.

---

## SECTION 0 — Executive Summary

**What we're building:** A local-first AI platform where (1) any service reaches any model via one OpenAI-compatible gateway, (2) MCP tools are centrally registered with policy controls and health checks, and (3) a dashboard manages service lifecycle (start/stop/restart, logs, health) through a secure, authenticated control plane.

**Biggest wins:** Single model endpoint for Open WebUI, OpenClaw, N8N; pluggable providers (Ollama today, vLLM/OpenAI-compatible tomorrow); safe ops from the dashboard without mounting docker.sock in the UI; audit trail for admin actions.

**Biggest risks:** Introducing a model gateway adds latency and a new failure mode; controller with docker.sock access is a high-value target; backwards compatibility with existing `OLLAMA_BASE_URL` configs must be preserved.

---

## SECTION 1 — Current State (Grounded)

### Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Host                                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐│
│  │ Open WebUI  │  │   N8N       │  │  OpenClaw   │  │  Cursor / Claude     ││
│  │ :3000       │  │ :5678       │  │ :18789      │  │  (external)          ││
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘│
│         │                │                │                     │           │
│         │ OLLAMA_BASE_URL │ MCP Client    │ OLLAMA + MCP        │ MCP       │
│         │                 │               │                     │           │
│  ┌──────▼─────────────────▼───────────────▼─────────────────────▼──────────┐│
│  │  Docker network: ai-toolkit_default                                      ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ ││
│  │  │ Ollama       │  │ MCP Gateway  │  │ Dashboard (FastAPI)             │ ││
│  │  │ :11434       │  │ :8811        │  │ :8080 — models, MCP, services  │ ││
│  │  │ (native API) │  │ docker.sock  │  │ (no docker.sock)                │ ││
│  │  └──────────────┘  └──────────────┘  └────────────────────────────────┘ ││
│  │  ┌──────────────┐  ┌──────────────┐                                     ││
│  │  │ ComfyUI      │  │ model-puller │                                     ││
│  │  │ :8188        │  │ (profile)    │                                     ││
│  │  └──────────────┘  └──────────────┘                                     ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Ollama:** Native API at `http://ollama:11434` (no `/v1`). Open WebUI, OpenClaw, N8N each point directly to it.
- **MCP Gateway:** Docker MCP Gateway with wrapper; reads `data/mcp/servers.txt` (comma-separated server names); reloads every 10s; mounts `docker.sock` to spawn MCP server containers.
- **Dashboard:** FastAPI app serving static HTML + REST APIs: `/api/ollama/*`, `/api/comfyui/*`, `/api/mcp/*`, `/api/services`. No docker.sock; health checks via HTTP to services.
- **Compose:** Single `docker-compose.yml`; `compose` / `compose.ps1` run `detect_hardware.py` then `docker compose`; optional `docker-compose.compute.yml` for GPU.

### What Already Satisfies G1–G3

| Goal | Current Support |
|------|-----------------|
| **G1: Any service → any model** | Partial. All services talk to Ollama directly. No unified endpoint; Open WebUI expects `OLLAMA_BASE_URL`, OpenClaw uses `OLLAMA_BASE_URL` + native API, N8N uses its own model config. No vLLM/OpenAI-compatible provider support. |
| **G2: Shared tools with policy** | Partial. MCP Gateway shares tools via `http://mcp-gateway:8811/mcp`. Dashboard can add/remove servers via `servers.txt`. No policy (allowlist/denylist per client), no health checks, no scopes. Secrets via `mcp/.env` + Docker secrets (optional, commented out). |
| **G3: Dashboard as control center** | Partial. Dashboard shows service health (HTTP checks), model inventory, MCP add/remove. No start/stop/restart, no logs tail, no image updates. No auth on dashboard API. |

### Pain Points / Gaps (Mapped to G1–G3)

| Gap | Goal | Description |
|-----|------|-------------|
| Multiple model endpoints | G1 | Each service configures Ollama separately. Adding vLLM or OpenAI-compatible would require per-service config. |
| No model router | G1 | No single `/v1/chat/completions` surface; N8N/Open WebUI expect different shapes. |
| MCP: no policy | G2 | All clients get all tools. No per-tool allowlist, rate limits, or capability scopes. |
| MCP: no health | G2 | Failing MCP servers stay enabled; no auto-disable. |
| MCP: secrets UX | G2 | Manual `mcp/.env` + compose secrets; no dashboard UI for secret binding. |
| No ops control | G3 | Dashboard cannot start/stop/restart services. Users run `docker compose` manually. |
| No audit | G3 | No record of who did what (model pull, MCP add, service restart). |
| No dashboard auth | G3 | Dashboard API is unauthenticated; suitable for localhost only. |

---

## SECTION 2 — Product Principles

1. **Local-first:** Single-command bring-up (`./compose up -d`). No cloud dependency for core flows. Data stays on host.
2. **Docker Compose as source of truth:** All services defined in compose. No Kubernetes. Controller talks to Docker socket for ops.
3. **Least privilege:** Dashboard never mounts docker.sock. Controller has minimal, allowlisted actions. Secrets outside plaintext where possible.
4. **One model endpoint:** Prefer OpenAI-compatible API (`/v1/chat/completions`, `/v1/embeddings`) as the canonical surface. Ollama adapter translates.
5. **Pluggable providers:** Adapter interface for Ollama, vLLM, OpenAI-compatible. Model registry lists available models per provider.
6. **Shared tools, guarded:** Central MCP registry with metadata. Per-client/tool allowlists. Health checks; auto-disable failing tools.
7. **Safe-by-default ops:** Controller requires auth. Destructive actions (restart, pull) support dry-run and confirmation. Audit log for admin actions.
8. **Minimize breaking changes:** Existing `OLLAMA_BASE_URL` continues to work. New model gateway is opt-in via env; services can point to gateway or Ollama directly during migration.
9. **Explicit trade-offs:** We accept added latency from model gateway proxy for interoperability. We accept controller complexity for secure ops.

---

## SECTION 3 — Target Architecture

### Components

- **Model Gateway:** Provider-agnostic proxy exposing OpenAI-compatible API. Routes to Ollama (default), vLLM, or external OpenAI-compatible endpoints. Model registry aggregates models from all providers.
- **Tool Registry + MCP Gateway enhancements:** Extend MCP Gateway with registry metadata (name, image, env schema, scopes), policy (allowlist/denylist, rate limits), health checks, and secrets binding. Dashboard manages registry.
- **Ops Controller:** Separate service with docker.sock access. Exposes authenticated REST API: start/stop/restart services, logs tail, health, image pull. Dashboard calls controller; controller never exposed to host by default (or via localhost-only).
- **Observability baseline:** Structured logs, optional metrics endpoint (Prometheus), audit events for admin actions (model pull, MCP add/remove, service ops).

### Data Flows

```
Model request:  Client → Model Gateway → [Ollama | vLLM | OpenAI-compatible]
Tool call:       Client → MCP Gateway (policy check) → MCP server container
Ops action:      Dashboard → Ops Controller (auth) → Docker socket
```

### Text Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Host                                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────────────────────┐│
│  │ Open WebUI  │ │   N8N       │ │  OpenClaw   │ │  Cursor / Claude             ││
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────────────┬──────────────┘│
│         │               │               │                        │                │
│         └───────────────┴───────────────┴────────────────────────┘                │
│                                    │                                              │
│                    OPENAI_BASE_URL (single endpoint)                              │
│                                    │                                              │
│  ┌─────────────────────────────────▼─────────────────────────────────────────────┐│
│  │  Docker network                                                                ││
│  │  ┌────────────────────┐  ┌────────────────────┐  ┌─────────────────────────┐ ││
│  │  │ Model Gateway      │  │ MCP Gateway        │  │ Ops Controller          │ ││
│  │  │ :11435 (or 8000)   │  │ :8811              │  │ :9000 (internal)        │ ││
│  │  │ /v1/chat/...       │  │ + registry          │  │ docker.sock             │ ││
│  │  │ /v1/embeddings     │  │ + policy + health   │  │ auth required           │ ││
│  │  └─────────┬──────────┘  └─────────┬──────────┘  └───────────┬─────────────┘ ││
│  │            │                        │                         ▲               ││
│  │            │                        │                         │               ││
│  │  ┌─────────▼──────────┐  ┌──────────▼──────────┐  ┌────────────┴─────────────┐ ││
│  │  │ Ollama :11434      │  │ MCP server          │  │ Dashboard :8080          │ ││
│  │  │ (native)           │  │ containers           │  │ (no docker.sock)         │ ││
│  │  └────────────────────┘  └─────────────────────┘  │ calls controller API   │ ││
│  │  ┌────────────────────┐                             └─────────────────────────┘ ││
│  │  │ vLLM (future)      │                                                         ││
│  │  └────────────────────┘                                                         ││
│  └────────────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Key Interfaces

#### A) Model Gateway API (OpenAI-compatible)

**Base URL:** `http://model-gateway:11435` (or configurable port)

| Endpoint | Method | Description |
|----------|--------|--------------|
| `/v1/models` | GET | List models from all providers (Ollama + future) |
| `/v1/chat/completions` | POST | Chat completion; routes to provider by model name |
| `/v1/embeddings` | POST | Embeddings; routes to provider |
| `/health` | GET | Gateway health |

**Request example (chat):**
```json
{
  "model": "deepseek-r1:7b",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": false
}
```

**Response:** OpenAI-compatible JSON. Model names include provider prefix when multiple providers: `ollama/deepseek-r1:7b`.

**Config convention:**
```yaml
# docker-compose
model-gateway:
  environment:
    - OLLAMA_URL=http://ollama:11434
    - DEFAULT_PROVIDER=ollama
    - OPENAI_COMPAT_PORT=11435
```

#### B) Tool Registry + MCP Gateway Policy API

**Registry format** (`data/mcp/registry.json` — new file):
```json
{
  "servers": {
    "duckduckgo": {
      "image": "mcp/duckduckgo",
      "scopes": ["search"],
      "allow_clients": ["*"],
      "rate_limit_rpm": 60,
      "timeout_sec": 30,
      "env_schema": {}
    },
    "github-official": {
      "image": "mcp/github-official",
      "scopes": ["github"],
      "allow_clients": ["open-webui", "openclaw"],
      "env_schema": {"GITHUB_PERSONAL_ACCESS_TOKEN": "required"}
    }
  }
}
```

**Policy API** (extend dashboard or MCP gateway):
- `GET /api/mcp/registry` — list servers with metadata
- `PUT /api/mcp/registry` — update registry (admin)
- `GET /api/mcp/health` — per-server health status

**servers.txt** remains for enabled list; registry adds metadata. Migration: if registry.json missing, infer from servers.txt with defaults.

#### C) Ops Controller API

**Base URL:** `http://ops-controller:9000` (internal to Docker network; dashboard calls it)

**Auth:** Bearer token from `OPS_CONTROLLER_TOKEN` (env). Generate: `openssl rand -hex 32`.

| Endpoint | Method | Description |
|----------|--------|--------------|
| `/health` | GET | Controller health |
| `/services` | GET | List compose services + status |
| `/services/{id}/start` | POST | Start service |
| `/services/{id}/stop` | POST | Stop service |
| `/services/{id}/restart` | POST | Restart service |
| `/services/{id}/logs` | GET | Tail logs (query: `tail=100`) |
| `/images/pull` | POST | Pull images for services (body: `{"services": ["ollama"]}`) |
| `/audit` | GET | Audit log (query: `limit=50`) |

**Request example (restart):**
```json
POST /services/ollama/restart
Authorization: Bearer <token>
{"confirm": true}
```

**Response:**
```json
{"ok": true, "service": "ollama", "action": "restarted"}
```

**Safety:** All mutating actions require `confirm: true`. Optional `dry_run: true` returns planned actions without executing.

---

## SECTION 4 — Workstreams (Detailed)

### WS1: Unified Model Access

**Provider abstraction:**
- Interface: `ModelProvider` with `list_models()`, `chat(messages, model, stream)`, `embed(texts, model)`.
- Ollama adapter: translate OpenAI request → Ollama native API; handle streaming.
- Model registry: aggregate `GET /api/tags` from Ollama; future: vLLM `/v1/models`, etc.

**Routing:**
- By model name: `ollama/deepseek-r1:7b` → Ollama; `deepseek-r1:7b` with single provider → Ollama.
- Future: by task type (chat vs embed), cost/latency (if multiple providers).

**Compatibility:**
- Open WebUI: set `OLLAMA_BASE_URL=http://model-gateway:11435` — requires gateway to accept Ollama-style requests OR Open WebUI to support OpenAI base URL. **Assumption:** Open WebUI supports `OPENAI_API_BASE`; we use OpenAI-compatible gateway and set that. If not, we add an Ollama-compatible proxy mode to the gateway.
- OpenClaw: `openclaw.json` supports `baseUrl` + `api`; add provider with `api: "openai"` and `baseUrl: "http://model-gateway:11435/v1"`.
- N8N: Use OpenAI-compatible node with base URL override.

**Edge cases:**
- Container networking: gateway reaches `ollama:11434`; clients reach `model-gateway:11435`.
- Auth: gateway optional API key for future; for local-first, none by default.
- Streaming: proxy streaming responses byte-for-byte.
- Embeddings: map `/v1/embeddings` to Ollama `/api/embeddings`.

### WS2: Shared Tools Everywhere (MCP)

**Registry format:** JSON with `servers` key; each server: `image`, `scopes`, `allow_clients`, `rate_limit_rpm`, `timeout_sec`, `env_schema`. Validation: image must be valid Docker ref; `allow_clients` is list or `["*"]`.

**Policy:**
- Allowlist: if `allow_clients` != `["*"]`, check client identity (e.g. `X-Client-ID` header or source IP for localhost). **Assumption:** Initial implementation uses `["*"]`; per-client allowlist in M2.
- Denylist: `deny_clients` array; checked before allowlist.
- Rate limits: per-tool RPM; 429 when exceeded.
- Timeouts: kill tool invocation after N seconds.

**Secrets:**
- Store in `mcp/.env`; mount as Docker secrets. Dashboard: "Configure secrets" links to docs; no plaintext secret input in UI initially.
- Env schema in registry documents required vars; validation at add-time.

**Health checks:**
- Periodic HTTP/SSE ping to MCP gateway for each server; if 3 failures, mark unhealthy and optionally disable.
- Dashboard shows green/yellow/red per tool.

**Developer UX:**
- Add tool in dashboard: select from catalog or paste Docker ref; registry updated; servers.txt updated.
- Discoverability: catalog with search; docs link to Docker MCP Catalog.

### WS3: Dashboard as Control Center (Ops)

**Controller design:**
- New service `ops-controller` in compose. Mounts `docker.sock` read-write. Listens on `9000` inside network only (no host port by default).
- Allowlisted actions: `docker compose up -d <svc>`, `docker compose stop <svc>`, `docker compose restart <svc>`, `docker compose logs -f --tail N <svc>`, `docker compose pull <svc>`.
- Implementation: Python + `docker` SDK or subprocess to `docker compose` in project directory.

**Dashboard integration:**
- Dashboard gets `OPS_CONTROLLER_URL` and `OPS_CONTROLLER_TOKEN`. Calls controller for start/stop/restart/logs.
- UI: each service card gets Start/Stop/Restart buttons; Logs opens modal with tail.
- CSRF: Same-origin; token in `Authorization` header. For localhost, sufficient.

**Audit:**
- Controller writes audit log: `{timestamp, action, service, actor: "dashboard"}`. Store in `data/ops-controller/audit.log` (append-only).
- Dashboard `/api/audit` proxies to controller or reads file.

**Safety:**
- Dry-run: `POST /services/ollama/restart` with `dry_run: true` returns `{"would": "restart ollama"}`.
- Confirmations: destructive actions require `confirm: true` in body.
- Failure modes: controller down → dashboard shows "Ops unavailable"; no fallback to docker.sock in dashboard.

---

## SECTION 5 — Implementation Plan

### Milestones

| Milestone | Outcomes | Timeline |
|-----------|----------|----------|
| **M0** | First PR: scaffolding, health aggregation, docs | &lt;1 day |
| **M1** | Model Gateway (Ollama adapter), Open WebUI + OpenClaw point to it | 1–2 weeks |
| **M2** | MCP registry + policy (allowlist, health), dashboard enhancements | 1–2 weeks |
| **M3** | Ops Controller + dashboard ops UI, audit | 1–2 weeks |
| **M4** | Observability (metrics, structured logs), security review | 1 week |

### M0 — First PR (See Section 6)

### M1 — Model Gateway

**User-visible:** Open WebUI and OpenClaw use `http://model-gateway:11435`; single endpoint for chat and embeddings.

**PR slices:**
1. **PR1:** Add `model-gateway` service (Python/FastAPI). Ollama adapter: `/v1/models` → proxy Ollama tags; `/v1/chat/completions` → translate to Ollama `/api/chat`; `/v1/embeddings` → Ollama `/api/embeddings`. No streaming in first slice.
2. **PR2:** Add streaming support for chat.
3. **PR3:** Update Open WebUI env to `OPENAI_API_BASE=http://model-gateway:11435/v1` (or equivalent). Update OpenClaw `openclaw.json.example` with model gateway provider.
4. **PR4:** Document migration; `.env.example` with `MODEL_GATEWAY_URL`; backward compat: if unset, services keep `OLLAMA_BASE_URL`.

**File-level changes:**
- Add `model-gateway/` (Dockerfile, main.py, adapters/ollama.py)
- `docker-compose.yml`: add `model-gateway` service
- `openclaw/openclaw.json.example`: add gateway provider
- `.env.example`: `MODEL_GATEWAY_URL`, `OPENAI_API_BASE`
- `docs/GETTING_STARTED.md`: update model setup

**Acceptance criteria:**
- Given model gateway running, When GET `/v1/models`, Then returns Ollama models in OpenAI format
- Given model gateway, When POST `/v1/chat/completions` with `model: deepseek-r1:7b`, Then returns completion from Ollama
- Given Open WebUI with `OPENAI_API_BASE` set, When user sends chat, Then response comes via gateway

### M2 — MCP Registry + Policy

**PR slices:**
1. **PR1:** Add `registry.json` schema and migration from `servers.txt`. Dashboard reads registry; falls back to servers.txt if no registry.
2. **PR2:** MCP gateway wrapper reads registry; apply `allow_clients` (initially `*` only). Add health check endpoint.
3. **PR3:** Dashboard: health status per tool; "Configure" link for secrets.
4. **PR4:** Rate limits and timeouts in gateway (if Docker MCP Gateway supports; else document as future).

**File-level changes:**
- Add `data/mcp/registry.json.example`
- `mcp/gateway-wrapper.sh` or new wrapper: read registry, pass to gateway
- `dashboard/app.py`: `/api/mcp/registry`, `/api/mcp/health`
- `dashboard/static/index.html`: health indicators, registry UI

### M3 — Ops Controller

**PR slices:**
1. **PR1:** Add `ops-controller` service. Implement `/health`, `/services`, `/services/{id}/start|stop|restart` with token auth.
2. **PR2:** Add `/services/{id}/logs`, `/images/pull`, audit log.
3. **PR3:** Dashboard: Start/Stop/Restart/Logs buttons; call controller API.
4. **PR4:** `OPS_CONTROLLER_TOKEN` in `.env.example`; document security.

**File-level changes:**
- Add `ops-controller/` (Dockerfile, main.py)
- `docker-compose.yml`: add `ops-controller`, dashboard env for controller URL/token
- `dashboard/app.py`: proxy to controller for ops
- `dashboard/static/index.html`: ops buttons, logs modal

### M4 — Observability + Security

**PR slices:**
1. **PR1:** Structured JSON logs for dashboard, controller, model gateway.
2. **PR2:** Optional `/metrics` (Prometheus) for gateway and controller.
3. **PR3:** Security review checklist; threat model doc; least-privilege verification.

**Test plan:**
- Contract tests: model gateway `/v1/models`, `/v1/chat/completions` request/response shape
- Smoke tests: `docker compose up -d` → all services healthy; dashboard loads; model pull works
- Ops tests: controller restart service → verify container restarted

---

## SECTION 6 — "First PR" (Do Now)

**Goal:** Improve architecture without breaking anything; create scaffolding for later work.

### Deliverable

1. **Health aggregation API** — Dashboard `/api/health` returns aggregated status of all services + MCP gateway. Enables future "platform health" view.
2. **Scaffolding** — Add `model-gateway/` and `ops-controller/` directories with minimal `README.md` and placeholder Dockerfiles (no functional code yet).
3. **Docs** — Add `docs/ARCHITECTURE.md` (short) linking to this RFC; update `GETTING_STARTED.md` with "Architecture" section.

### Exact Steps

1. **Add `/api/health` to dashboard**
   - In `dashboard/app.py`, add:
     ```python
     @app.get("/api/health")
     async def health():
         results = []
         for svc in SERVICES:
             ok, err = await _check_service(svc["check"]) if svc.get("check") else (None, "")
             results.append({"id": svc["id"], "ok": ok, "error": err})
         all_ok = all(r["ok"] for r in results if r["ok"] is not None)
         return {"ok": all_ok, "services": results}
     ```

2. **Create scaffolding**
   - `model-gateway/README.md`: "Model Gateway — OpenAI-compatible proxy. See docs/ARCHITECTURE_RFC.md."
   - `model-gateway/Dockerfile`: `FROM python:3.12-slim` + `CMD ["echo", "placeholder"]`
   - `ops-controller/README.md`: "Ops Controller — Secure Docker Compose control plane. See docs/ARCHITECTURE_RFC.md."
   - `ops-controller/Dockerfile`: Same placeholder.

3. **Add docs**
   - `docs/ARCHITECTURE.md`: 1-page summary with diagram, link to ARCHITECTURE_RFC.md.
   - `docs/GETTING_STARTED.md`: Add "Architecture" bullet under Next steps.

4. **Tests**
   - Add `tests/test_dashboard_health.py`: `GET /api/health` returns 200 and `ok` boolean.

### Suggested Commit Outline

```
commit 1: Add /api/health aggregation endpoint to dashboard
  - dashboard/app.py: add health() route

commit 2: Add model-gateway and ops-controller scaffolding
  - model-gateway/README.md, Dockerfile
  - ops-controller/README.md, Dockerfile

commit 3: Add architecture docs
  - docs/ARCHITECTURE.md
  - docs/GETTING_STARTED.md: link to architecture

commit 4: Add dashboard health API test
  - tests/test_dashboard_health.py
  - pytest in CI or Makefile target
```

### Acceptance Criteria

- **Given** dashboard running, **When** GET `/api/health`, **Then** returns 200 with `ok` and `services` array
- **Given** repo root, **When** `ls model-gateway ops-controller`, **Then** both directories exist with README and Dockerfile
- **Given** `pytest tests/`, **When** run, **Then** health test passes

---

## SECTION 7 — Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Model gateway latency** | Keep gateway thin; stream passthrough. Benchmark: &lt;10ms overhead. Allow direct Ollama URL as escape hatch. |
| **Controller compromise** | Token in env; no default token. Document: never expose controller port to network. Least privilege: only compose project directory. |
| **Backwards compatibility** | Model gateway opt-in. `OLLAMA_BASE_URL` remains valid. Migration path in docs. |
| **MCP policy complexity** | Start with `allow_clients: ["*"]`. Add per-client in M2. |
| **Performance: model list** | Cache Ollama tags for 60s. Gateway `/v1/models` returns cached. |
| **Secret handling** | No secrets in dashboard UI initially. Link to mcp/.env + Docker secrets docs. |
| **OpenClaw browser worker SSRF** | Egress blocks for 100.64/10, RFC1918, 169.254.169.254. See Section 9. |

---

## SECTION 8 — Open Questions

1. **Open WebUI OpenAI compatibility:** Does Open WebUI support `OPENAI_API_BASE` for chat? If not, do we need an Ollama-compatible mode in the gateway?
2. **N8N model node:** Which N8N node (OpenAI, Ollama, custom) is used? Does it support base URL override?
3. **MCP Gateway policy:** Does Docker MCP Gateway support per-request policy (allowlist, rate limit) or do we need a sidecar/proxy?
4. **Controller scope:** Should controller manage only ai-toolkit compose, or any compose project? (Assumption: ai-toolkit only.)
5. **Audit retention:** How long to keep audit log? Rotate by size or time?
6. **Multi-provider model naming:** Use `provider/model` (e.g. `ollama/deepseek-r1:7b`) or flat namespace with provider in metadata?
7. **Dashboard auth:** For Tailscale/group use, add simple password or token auth to dashboard? Timeline?
8. **vLLM priority:** When to add vLLM adapter? After M1 stable.
9. **ComfyUI in model gateway:** ComfyUI is not an LLM API. Exclude from model gateway; keep separate in dashboard.
10. **Rollback:** If model gateway fails, can users set `OLLAMA_BASE_URL` back to `http://ollama:11434` and restart? (Yes — document.)

---

## SECTION 9 — OpenClaw Security & Trust Boundary

*Improving security and ensuring safety when running OpenClaw in Docker with Tailscale.*

### Core Goal

Run OpenClaw with a strict trust boundary:

- **Controller/UI = trusted** — secrets, tools, orchestration
- **Browser worker = untrusted-ish** — renders/explores the web; no secrets; disposable

### Components

#### 1) Controller / UI (trusted)

**Responsibilities:**

- Hosts the UI + API you interact with
- Stores credentials (LLM keys, tool tokens, etc.)
- Orchestrates workflows and delegates browsing tasks to the browser worker

**Exposure:**

- **Not public**
- Bind UI to localhost only; access via Tailscale (tailnet)

#### 2) Browser worker (untrusted)

**Responsibilities:**

- Runs a real browser (Chrome/Playwright-style) for dynamic sites
- Provides artifacts back to controller (DOM/text/screenshots/links)

**Security posture:**

- **No secrets**
- **No host mounts**
- Tight outbound rules (prevents SSRF / network pivot)

### Interaction Model

```
User → (Tailnet) → Controller/UI → (internal Docker network) → Browser worker → Internet
```

Controller sends browse jobs (URL + actions) to the browser worker and receives artifacts. Controller then summarizes/extracts/decides next steps.

### Tailnet (Tailscale) Stance

- Keep OpenClaw UI **off the public internet**
- Prefer **Tailscale Serve** for tailnet-only access
- Avoid Funnel unless intentional public exposure

### Hardening Stance (Web Crawling)

**Main threat:** SSRF / pivot into private networks + secrets exposure.

Browser worker must be prevented from reaching:

- Tailnet range **100.64.0.0/10**
- RFC1918 private nets **10/8, 172.16/12, 192.168/16**
- Cloud metadata **169.254.169.254**

Also re-check destinations on redirects and protect against DNS rebinding.

**Enforcement:** Apply outside the container where possible (host firewall / `DOCKER-USER` chain), not just in-container rules.

### Discord Stance

- **Yes**, Discord is the default input channel into the controller (same workflows as UI), gated by allowlists/pairing policies
- Discord should **not** talk directly to the browser worker

### API Interaction Stance

- Privileged API calls should be **controller-only** (keys live in controller)
- Browser worker may "call APIs" only indirectly as part of page loads (XHR/JS); it should **not** be given your credentials
- If you need real API access during a workflow: controller calls API → passes results into the plan

### MCP Stance

- Browser worker is driven via **CDP** (Chrome DevTools Protocol) using `BROWSER_CDP_URL`
- **CDP ≠ MCP** — the browser worker is not "put into an MCP"
- MCP (if used) is a controller-side tool integration concept, not the browser sidecar

### Docker Compose Stance (Key Choices)

| Choice | Value |
|--------|-------|
| UI binding | Host **6666** → container **8080** — `127.0.0.1:6666:8080` |
| Browser CDP | `BROWSER_CDP_URL=http://browser:9222` (internal only) |
| Network | Controller and browser share only an internal Docker network |
| Mounts | Controller: small persistent `/data` volume; Browser: optional profile volume, ideally no host paths |

### Minimal Operational Notes

- Access UI via: `http://127.0.0.1:6666` (or via Tailscale Serve pointing at that port)
- Ensure secrets only exist in controller environment/volumes, not browser
- Add egress blocks for browser worker as a baseline before heavy crawling

---

## Appendix: Config Conventions

### Environment Variables (New/Updated)

| Variable | Service | Description |
|----------|---------|-------------|
| `MODEL_GATEWAY_URL` | dashboard, open-webui, openclaw, n8n | `http://model-gateway:11435` when using gateway |
| `OPENAI_API_BASE` | open-webui | `http://model-gateway:11435/v1` (if supported) |
| `OPS_CONTROLLER_URL` | dashboard | `http://ops-controller:9000` |
| `OPS_CONTROLLER_TOKEN` | dashboard, ops-controller | Bearer token for controller API |
| `OLLAMA_URL` | model-gateway | `http://ollama:11434` (gateway's upstream) |

### Folder Structure (Target)

```
LLM-toolkit/
├── dashboard/           # existing
├── mcp/                 # existing + registry
├── model-gateway/       # NEW
├── ops-controller/      # NEW
├── openclaw/
├── scripts/
├── data/
│   ├── mcp/
│   │   ├── servers.txt
│   │   └── registry.json  # NEW
│   └── ops-controller/
│       └── audit.log      # NEW
├── tests/               # NEW or extend
├── docs/
│   ├── ARCHITECTURE.md   # NEW
│   └── ARCHITECTURE_RFC.md
├── docker-compose.yml
└── .env.example
```

### Rollback Plan

1. **Model gateway:** Set `OLLAMA_BASE_URL=http://ollama:11434` (or `OLLAMA_BASE_URL` for Open WebUI) in env; stop model-gateway service. Restart affected services.
2. **Ops controller:** Remove controller from compose; remove ops buttons from dashboard. No data loss.
3. **MCP registry:** Delete `registry.json`; gateway falls back to `servers.txt` only. Policy features disabled.
