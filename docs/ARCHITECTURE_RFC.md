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

*Grounded in the codebase and this document (Section 1) as of 2025-02-28.*

### Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Host                                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐│
│  │ Open WebUI  │  │   N8N       │  │  OpenClaw   │  │  Cursor / Claude        ││
│  │ :3000       │  │ :5678       │  │ :18789      │  │  (external)             ││
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────────────┬─────────────┘│
│         │                │                │                      │              │
│         │ OLLAMA_BASE_URL │ MCP Client    │ gateway provider     │ MCP         │
│         │ or OPENAI_API  │               │ + MCP gateway        │             │
│  ┌──────▼────────────────▼────────────────▼──────────────────────▼────────────┐│
│  │  Docker network: ai-toolkit_default                                          ││
│  │  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐  ┌────────────┐ ││
│  │  │ Model Gateway  │  │ MCP Gateway  │  │ Ops Controller  │  │ Dashboard  │ ││
│  │  │ :11435         │  │ :8811        │  │ :9000 (int)     │  │ :8080      │ ││
│  │  │ /v1/*          │  │ docker.sock  │  │ docker.sock     │  │ no sock    │ ││
│  │  └───────┬────────┘  └──────────────┘  └────────────────┘  └─────┬──────┘ ││
│  │          │                                                          │        ││
│  │  ┌───────▼────────┐  ┌──────────────┐                              │        ││
│  │  │ Ollama :11434   │  │ ComfyUI     │  Dashboard → Ops Controller    │        ││
│  │  │ (native API)    │  │ :8188       │  for restart/logs             │        ││
│  │  └─────────────────┘  └─────────────┘                               │        ││
│  └─────────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────┘
```

- **Model Gateway:** Exists. OpenAI-compatible at `http://model-gateway:11435` — `/v1/models`, `/v1/chat/completions`, `/v1/embeddings`. Proxies to Ollama. Records throughput to dashboard.
- **Ollama:** Native API at `http://ollama:11434`. Open WebUI defaults to it via `OLLAMA_BASE_URL`; OpenClaw has both `ollama` and `gateway` providers.
- **MCP Gateway:** Docker MCP Gateway + `gateway-wrapper.sh`; reads `data/mcp/servers.txt`; reloads every 10s; mounts `docker.sock`. Does NOT read `registry.json`.
- **Ops Controller:** Exists. Auth via `OPS_CONTROLLER_TOKEN`; `/services/{id}/restart`, `/logs`, `/audit`; audit log in `data/ops-controller/audit.log`.
- **Dashboard:** FastAPI — `/api/ollama/*`, `/api/comfyui/*`, `/api/mcp/*`, `/api/services`, `/api/health`, `/api/ops/*`. Restart/Logs buttons when token set. No docker.sock.
- **Compose:** `compose` / `compose.ps1` run `detect_hardware.py` then `docker compose`; `docker-compose.compute.yml` for GPU.

### What Already Satisfies G1–G5

| Goal | Current Support |
|------|-----------------|
| **G1: Any service → any model** | Partial. Model Gateway exists; Open WebUI defaults to Ollama; OpenClaw uses gateway provider. No vLLM/OpenAI-compatible provider. |
| **G2: Shared tools with policy** | Partial. MCP Gateway shares tools; dashboard add/remove via `servers.txt`. `registry.json.example` exists but gateway does not use it. No policy, health, or scopes. |
| **G3: Dashboard as control center** | Good. Ops controller + Restart/Logs buttons. No Start/Stop in UI. |
| **G4: Security + auditing** | Partial. Audit log exists (JSONL); no formal schema; no correlation IDs; dashboard unauthenticated. |
| **G5: Docker best practices** | Partial. No explicit healthchecks in compose; no non-root; no resource limits. |

### Pain Points / Gaps (Mapped to G1–G5)

| Gap | Goal | Description |
|-----|------|-------------|
| Open WebUI defaults to Ollama | G1 | `OLLAMA_BASE_URL` default is direct Ollama; `OPENAI_API_BASE` must be set for gateway. |
| No vLLM provider | G1 | Single provider (Ollama) only. |
| MCP: registry unused | G2 | `registry.json` exists; gateway wrapper reads only `servers.txt`. No policy enforcement. |
| MCP: no health | G2 | Failing MCP servers stay enabled. |
| No Start/Stop in UI | G3 | Controller has start/stop; dashboard only exposes Restart. |
| Audit schema informal | G4 | Log format ad-hoc; no correlation_id, no export. |
| No dashboard auth | G4 | Dashboard API unauthenticated. |
| No Docker hardening | G5 | Missing healthchecks, non-root, resource limits, log rotation. |

### OpenClaw: Current Integration Map

| Aspect | Current State |
|--------|----------------|
| **Models** | `openclaw.json` has `gateway` (baseUrl: `http://model-gateway:11435/v1`, api: `openai-completions`) and `ollama` (baseUrl: `http://ollama:11434`, api: `ollama`). `merge_gateway_config.py` adds gateway if missing. |
| **MCP** | `mcp.servers.gateway` → `http://mcp-gateway:8811/mcp`, transport `streamable-http`. |
| **Config sync** | `openclaw-config-sync` runs before gateway; merges gateway provider into `data/openclaw/openclaw.json`. |
| **Networking** | Gateway and MCP reachable via Docker service names. |

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

#### D) Audit Event Pipeline (Schema + Storage + Export)

**Schema:** See WS4. Events written to `data/ops-controller/audit.log` (JSONL, append-only).

**Sources:** Ops controller (restart, start, stop, pull, logs access); future: dashboard (model pull, MCP add/remove), model gateway (optional high-value actions).

**Export:** `GET /audit?limit=50&format=json` (controller). Dashboard can proxy. Optional: `?since=ISO8601` for time-range.

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
- Embeddings: map `/v1/embeddings` to Ollama `/api/embed`.

**OpenClaw-specific:**
- **Config keys:** `models.providers.gateway.baseUrl` = `http://model-gateway:11435/v1`; `api` = `openai-completions`; `headers.X-Service-Name` = `openclaw` (for dashboard throughput tracking).
- **Backward compat:** `merge_gateway_config.py` adds gateway provider if missing. Existing `ollama` provider remains; users can choose gateway or ollama per model.
- **Migration:** No breaking change. Users with only `ollama` keep working; add gateway for unified endpoint + throughput visibility.

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

**OpenClaw-specific:**
- **MCP endpoint:** OpenClaw uses `mcp.servers.gateway.url` = `http://mcp-gateway:8811/mcp`, transport `streamable-http`. Single gateway server; all tools from MCP Gateway.
- **Per-agent policies:** Future: registry `allow_clients` could include `openclaw`; gateway would check `X-Client-ID: openclaw` (or similar) before routing. Today: all clients get all enabled tools.
- **Compatibility:** Existing `openclaw.json` with `mcp.servers.gateway` continues to work. No config change needed.

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

### WS4: Auditing, Security, and Threat Model (Required)

**Threat model table:**

| Asset | Threat | Mitigation |
|-------|--------|------------|
| docker.sock | Container escape, host compromise | Ops controller only; allowlist; no dashboard mount |
| Ops controller | Token theft, privilege escalation | Token in env; no default; never expose port to network |
| MCP tools | SSRF (browser worker → private nets) | Egress blocks: 100.64/10, 10/8, 172.16/12, 192.168/16, 169.254.169.254 |
| Tool calls | Prompt injection via tool output | Allowlists; structured tool calls; sandbox where possible |
| Secrets | Exfiltration via tools | No secrets in browser worker; controller-only API keys |
| Dashboard | Unauthenticated admin | Localhost-only; add token/password for Tailscale/group use |

**AuthN/AuthZ:** Local tokens (`OPS_CONTROLLER_TOKEN`, `OPENCLAW_GATEWAY_TOKEN`). Optional OAuth later. RBAC: dashboard = ops caller; controller = executor.

**Audit event schema (JSON):**

```json
{
  "ts": "2025-02-28T12:34:56.789Z",
  "action": "restart",
  "resource": "ollama",
  "actor": "dashboard",
  "result": "ok",
  "correlation_id": "req-abc123",
  "metadata": {"tail": 100}
}
```

**Fields:** `ts` (ISO8601), `action` (start|stop|restart|pull|mcp_add|mcp_remove|model_pull|model_delete), `resource` (service/model/tool id), `actor` (dashboard|cli), `result` (ok|error), `correlation_id` (optional), `metadata` (extra).

**Storage:** Append-only `data/ops-controller/audit.log` (JSONL). Rotate by size (e.g. 10MB) or time. Export: `GET /audit?limit=N&format=json`.

**Correlation IDs:** Model gateway adds `X-Request-ID`; controller propagates; audit entries include it for tracing model→ops flows.

**Secret handling:** Compose secrets or `mcp/.env` (not committed). No plaintext in dashboard UI. Document rotation in runbooks.

### WS5: Best-in-Class Docker/Compose & Repo Organization (Required)

**Compose hardening checklist (apply to current files):**

| Check | Current | Action |
|-------|---------|--------|
| Non-root | Not set | Add `user: "1000:1000"` where feasible (dashboard, model-gateway) |
| Healthchecks | Missing | Add `healthcheck` to ollama, model-gateway, dashboard, mcp-gateway |
| Resource limits | Missing | Add `deploy.resources.limits.memory` for critical services |
| Log rotation | Default | Add `logging: driver: json-file, options: max-size: 10m, max-file: 3` |
| Pinned images | Partial | Ollama 0.17.4 ✓; open-webui v0.8.4 ✓; add digest for critical |
| Read-only rootfs | No | Add `read_only: true` + tmpfs where needed (model-gateway) |
| Drop capabilities | No | Add `cap_drop: [ALL]` where possible |

**Networks/ports:** Model gateway 11435, MCP 8811, dashboard 8080 exposed. Ops controller: no host port (internal only).

**Repo structure (target):**

```
LLM-toolkit/
├── dashboard/           # existing
├── mcp/                 # existing + registry
├── model-gateway/       # existing
├── ops-controller/      # existing
├── openclaw/
├── scripts/
├── data/                # runtime data (gitignored)
│   ├── mcp/
│   ├── ops-controller/
│   └── ...
├── tests/               # contract + smoke tests
├── docs/
│   ├── ARCHITECTURE_RFC.md
│   ├── runbooks/
│   └── audit/
├── docker-compose.yml
└── .env.example
```

**Operational runbooks:** Add `docs/runbooks/BACKUP_RESTORE.md`, `UPGRADE.md`, `TROUBLESHOOTING.md` (extend existing).

---

## SECTION 5 — Implementation Plan

### Milestones (Current State: M1, M3 largely done)

| Milestone | Outcomes | Status |
|-----------|----------|--------|
| **M0** | First PR: audit schema + Docker hardening + docs | Next |
| **M1** | Model Gateway, OpenClaw gateway provider | Done |
| **M2** | MCP registry + policy (allowlist, health) | Pending |
| **M3** | Ops Controller + dashboard Restart/Logs | Done |
| **M4** | Observability, security review, Docker hardening | Pending |

### M0 — First PR (See Section 6)

Delivers: formal audit schema, one Docker hardening improvement, docs. No breaking changes.

### M1 — Model Gateway ✓ (Done)

Model gateway exists. OpenClaw has gateway provider. Open WebUI can use `OPENAI_API_BASE` (opt-in).

**Remaining:** Default Open WebUI to gateway in `.env.example` (optional); add vLLM adapter (future).

### M2 — MCP Registry + Policy

**PR slices:**
1. **PR1:** MCP gateway wrapper reads `registry.json` when present; fallback to `servers.txt`. No policy yet.
2. **PR2:** Dashboard `/api/mcp/health` — probe each server; return status. Dashboard UI: health indicators.
3. **PR3:** Apply `allow_clients` in gateway (requires proxy or Docker MCP Gateway extension; document if not feasible).
4. **PR4:** Rate limits/timeouts — document or implement if gateway supports.

**File-level changes:**
- `mcp/gateway-wrapper.sh`: read registry, merge with servers.txt
- `dashboard/app.py`: `/api/mcp/health`
- `dashboard/static/index.html`: health badges per tool

### M3 — Ops Controller ✓ (Done)

Controller exists. Dashboard has Restart/Logs. Audit log in place.

**Remaining:** Add Start/Stop buttons; formalize audit schema (M0).

### M4 — Observability + Docker Hardening

**PR slices:**
1. **PR1:** Add healthchecks to `docker-compose.yml` for ollama, model-gateway, dashboard, mcp-gateway.
2. **PR2:** Add log rotation: `logging: options: max-size: 10m, max-file: 3` for key services.
3. **PR3:** Structured JSON logs (optional); `/metrics` (optional).
4. **PR4:** Security checklist; threat model doc.

**Quality bar:**
- **Tests:** Contract test for model gateway `/v1/models`; smoke test `docker compose up -d` → health.
- **Security:** Threat model table; least-privilege verification; no secrets in logs.
- **Performance:** Model list &lt;2s; tool invocation &lt;30s default.
- **Break-glass:** Document: reset `OPS_CONTROLLER_TOKEN`; restore `data/` from backup; disable MCP via servers.txt.

---

## SECTION 6 — "First PR" (Do Now)

**Goal:** Improve architecture without breaking anything. Formalize audit schema, add one Docker hardening improvement, document.

### Deliverable

1. **Audit event schema** — Define and document schema; update ops-controller to emit compliant events.
2. **Docker hardening** — Add healthchecks to ollama, model-gateway, dashboard, mcp-gateway in `docker-compose.yml`.
3. **Docs** — Add `docs/audit/SCHEMA.md`; link from ARCHITECTURE_RFC.

### Exact Steps

1. **Formalize audit schema**
   - Add `docs/audit/SCHEMA.md` with JSON schema and examples.
   - In `ops-controller/main.py`, update `_audit()` to include `resource`, `result`, optional `correlation_id`:
     ```python
     def _audit(action: str, resource: str = "", result: str = "ok", detail: str = "", correlation_id: str = ""):
         entry = {
             "ts": datetime.utcnow().isoformat() + "Z",
             "action": action,
             "resource": resource or "",
             "actor": "dashboard",
             "result": result,
             "detail": detail,
         }
         if correlation_id:
             entry["correlation_id"] = correlation_id
         ...
     ```

2. **Add healthchecks to docker-compose.yml**
   - ollama: `healthcheck: test: ["CMD", "curl", "-f", "http://localhost:11434/api/version"]`
   - model-gateway: `healthcheck: test: ["CMD", "curl", "-f", "http://localhost:11435/health"]`
   - dashboard: `healthcheck: test: ["CMD", "curl", "-f", "http://localhost:8080/api/health"]`
   - mcp-gateway: `healthcheck: test: ["CMD", "curl", "-f", "http://localhost:8811/mcp"]` (or wget if curl absent)

3. **Add log rotation** (one service as example)
   - dashboard: `logging: driver: json-file, options: {max-size: "10m", max-file: "3"}`

4. **Docs**
   - `docs/audit/SCHEMA.md`: schema, field descriptions, example events.

### Suggested Commit Outline

```
commit 1: Add audit event schema and update ops-controller
  - docs/audit/SCHEMA.md
  - ops-controller/main.py: _audit() with resource, result, correlation_id

commit 2: Add healthchecks to docker-compose.yml
  - docker-compose.yml: healthcheck for ollama, model-gateway, dashboard, mcp-gateway

commit 3: Add log rotation for dashboard
  - docker-compose.yml: logging options for dashboard

commit 4: Add tests for audit and health
  - tests/test_ops_controller_audit.py (if tests/ exists)
  - tests/test_dashboard_health.py
```

### Acceptance Criteria

- **Given** ops-controller restarts a service, **When** audit log is read, **Then** entry has `ts`, `action`, `resource`, `actor`, `result` fields
- **Given** `docker compose up -d`, **When** `docker compose ps`, **Then** ollama, model-gateway, dashboard show `healthy` (or `starting` then `healthy`)
- **Given** `docs/audit/SCHEMA.md`, **When** read, **Then** schema is documented with examples

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
│   ├── ARCHITECTURE_RFC.md
│   └── runbooks/
├── docker-compose.yml
└── .env.example
```

### Rollback Plan

1. **Model gateway:** Set `OLLAMA_BASE_URL=http://ollama:11434` (or `OLLAMA_BASE_URL` for Open WebUI) in env; stop model-gateway service. Restart affected services.
2. **Ops controller:** Remove controller from compose; remove ops buttons from dashboard. No data loss.
3. **MCP registry:** Delete `registry.json`; gateway falls back to `servers.txt` only. Policy features disabled.
