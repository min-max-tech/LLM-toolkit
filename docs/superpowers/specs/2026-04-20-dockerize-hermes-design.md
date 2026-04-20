# Dockerize Hermes Agent — Design

**Date:** 2026-04-20
**Status:** Approved for planning
**Context:** Phase 3 of Hermes migration (Phase 1: host-mode install, Phase 2: OpenClaw removal). This phase moves Hermes from a host-mode install into the Docker stack as two first-class compose services, achieving atomic `docker compose up -d` for the whole system.

## Goal

Replace the host-mode Hermes install (bootstrap script, global wrapper, `vendor/hermes-agent/` clone) with two Docker compose services — `hermes-gateway` and `hermes-dashboard` — that come up with the stack, restart on failure, depend on healthy model-gateway/mcp-gateway/dashboard, and show up green on the Ordo dashboard via internal-DNS health probes.

After this change:
- `docker compose up -d` brings Hermes online alongside llamacpp, model-gateway, mcp-gateway, etc.
- `docker compose down` takes it offline.
- `docker compose logs -f hermes-gateway` streams logs.
- No PowerShell / Git Bash / WSL2 rituals. No Windows Task Scheduler. No global `hermes` wrapper.
- Survives Windows reboots via Docker Desktop autostart.

## Non-goals

- Changing the host-side Discord Developer Portal setup or env-var names — those stay identical to phase-2.
- Changing Hermes's internal config schema (we still write the same `model.*` and `mcp_servers.*` keys).
- Publishing or building a Hermes Docker image for non-Ordo-stack use.
- Restructuring the existing stack's services.
- Switching to Docker secrets (future hardening, not this PR).
- Providing a parallel host-mode install path — host mode is deleted (see Q2 decision in brainstorm).

## Branch

`feat/dockerize-hermes` off `main` at `61c14a7`.

## Architecture

Two new compose services sharing one image built by one Dockerfile.

### Service layout

| Service | Process | Ports | Network |
|---|---|---|---|
| `hermes-gateway` | `hermes gateway` (messaging platforms + cron scheduler) | none exposed on host (outbound only, to Discord WebSocket) | `frontend`, `backend` |
| `hermes-dashboard` | `hermes dashboard --port 9119 --host 0.0.0.0 --no-open` | `${HERMES_DASHBOARD_PORT:-9119}:9119` | `frontend`, `backend` |

Both use the same built image (`ordo-ai-stack-hermes:latest`). Both mount the same state volume (`data/hermes`). Both mount the repo workspace (`BASE_PATH` → `/workspace`). Differences are purely the `command:` and port mapping.

### Dockerfile

Multi-stage build under `hermes/Dockerfile`:

1. **Stage `web-builder`** (based on `node:20-slim`):
   - Clones `NousResearch/hermes-agent` at the pinned SHA.
   - `cd web && npm install && npm run build`.
   - Output: `/build/hermes-agent/hermes_cli/web_dist/` (SPA bundle).
2. **Stage `runtime`** (based on `python:3.11-slim`):
   - Installs `uv`, `git`, `curl`.
   - Creates user `hermes` (uid 1000, home `/home/hermes`).
   - Clones `NousResearch/hermes-agent` at the same pinned SHA into `/opt/hermes-agent/`.
   - `uv venv && uv pip install -e ".[all]"` inside `/opt/hermes-agent/.venv/`.
   - Copies built `web_dist/` from the web-builder stage.
   - Applies the `os.kill` Windows compatibility patches via the same sed-style idempotent Python patcher used in the host-mode bootstrap (so the patch survives re-builds and isn't lost).
   - Copies `hermes/entrypoint.sh` (below).
   - `ENTRYPOINT ["/entrypoint.sh"]`.

The pinned SHA is a Docker build arg: `ARG HERMES_PINNED_SHA=dcd763c284086afd5ddee4fdcd86daaf534916ab`. To refresh, edit the Dockerfile and `docker compose build hermes-gateway hermes-dashboard`.

### Entrypoint

`hermes/entrypoint.sh` seeds `/home/hermes/.hermes/config.yaml` on every container start (idempotent — only writes keys that are missing, not empty). Then `exec "$@"` to run the compose-supplied `command`.

Seeded values:
```yaml
model:
  provider: custom
  base_url: http://model-gateway:11435/v1
  api_key: <LITELLM_MASTER_KEY from env>
  default: local-chat
mcp_servers:
  gateway:
    url: http://mcp-gateway:8811/mcp
```

Existing `data/hermes/config.yaml` on disk (from phase-1 host mode) is preserved; operator state (sessions, memories, skills) migrates transparently.

### Environment variables (explicit list per service)

Both services receive:
- `PYTHONIOENCODING=utf-8`
- `LITELLM_MASTER_KEY` (passed through so entrypoint can seed `model.api_key`)
- `HERMES_HOME=/home/hermes/.hermes` (fixed inside container; not configurable)

`hermes-gateway` additionally receives:
- `DISCORD_BOT_TOKEN`
- `DISCORD_ALLOWED_USERS`
- `DISCORD_ALLOWED_CHANNELS`
- `DISCORD_ALLOWED_ROLES`
- `DISCORD_REQUIRE_MENTION`
- `DISCORD_FREE_RESPONSE_CHANNELS`
- `DISCORD_HOME_CHANNEL`
- `DISCORD_AUTO_THREAD`
- `DISCORD_REACTIONS`
- `TELEGRAM_BOT_TOKEN`

No broad `env_file: .env` — each service gets only what it needs (Q6d decision).

### Volumes

Both services:
- `${BASE_PATH:-.}:/workspace:rw` — Hermes can read/write the Ordo repo (same scope as `ops-controller`).
- `${DATA_PATH:-${BASE_PATH:-.}/data}/hermes:/home/hermes/.hermes:rw` — persistent config + sessions + skills + FTS5 DB.

No Docker socket mount — MCP gateway handles container orchestration needs.
No whole-drive mount — out of scope.

### Depends_on

Both services declare:
```yaml
depends_on:
  model-gateway:
    condition: service_healthy
  mcp-gateway:
    condition: service_healthy
  dashboard:
    condition: service_healthy
```

This serializes startup: Hermes only starts once the stack is actually usable, preventing the "gateway starts, model-gateway not ready, errors out, restart loops" failure mode.

### Healthchecks

- `hermes-gateway`: `test -f /home/hermes/.hermes/gateway.pid`. Hermes writes this file once the messaging platforms have registered; presence indicates the process is past startup. `hermes gateway status` would be more thorough but only works for systemd/launchd-registered installations (which Docker-mode isn't). 60s `start_period`.
- `hermes-dashboard`: `curl -sf http://localhost:9119/` returns 2xx. 30s `start_period`.

Both match the existing stack's healthcheck style (lightweight, in-container).

### Restart policy

`unless-stopped` on both. Matches every other long-running service in the stack.

### Logging

Both services use the stack's standard json-file driver with 10MB x 3 rotation:

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

## Dashboard integration

`dashboard/services_catalog.py` — change the `hermes` entry from:

```python
"check": "http://host.docker.internal:9119/",
"hint": "Start it with: ./scripts/start-hermes-host.sh --dashboard",
```

To:

```python
"check": "http://hermes-dashboard:9119/",
"hint": "Managed by docker compose. Logs: docker compose logs hermes-dashboard",
```

This makes the probe use internal DNS (matches every other catalog entry) and is always correct — no more "false unhealthy if operator forgot to start host-mode."

## File-change summary

### New files

| Path | Responsibility |
|---|---|
| `hermes/Dockerfile` | Multi-stage build: web UI + Python runtime |
| `hermes/entrypoint.sh` | Idempotent config-seeding + exec |
| `hermes/.dockerignore` | Keep build context minimal |
| `tests/test_hermes_docker.py` | Static lint: compose service definitions, catalog points at internal DNS, dockerfile syntax |

### Modified files

| Path | Change |
|---|---|
| `docker-compose.yml` | Add `hermes-gateway` + `hermes-dashboard` services |
| `dashboard/services_catalog.py` | Switch Hermes health probe to internal DNS |
| `docs/hermes-agent.md` | Rewrite: remove host-mode walkthrough, add Docker walkthrough |
| `CHANGELOG.md` | New `### Changed` entry under `[Unreleased]` |
| `.env.example` | Remove host-mode-specific Hermes lines (`HERMES_HOME`, `HERMES_PINNED_SHA`). Keep Discord/Telegram block |

### Deleted files

| Path | Reason |
|---|---|
| `scripts/start-hermes-host.sh` | Host mode removed |
| `tests/test_start_hermes_host.py` | Covers host mode |

### Operator-disk cleanup (not a commit — doc note)

Operator deletes manually after this merges:
- `C:\Users\lynch\.local\bin\hermes` and `hermes.cmd` (wrapper scripts)
- `C:\dev\AI-toolkit\vendor\hermes-agent\` (gitignored source clone — frees ~500MB)

## Sequencing

Each bucket becomes one or more plan tasks. Order chosen to maintain a green build at each step.

1. Add `hermes/Dockerfile`, `hermes/entrypoint.sh`, `hermes/.dockerignore`.
2. Add `hermes-gateway` and `hermes-dashboard` services to `docker-compose.yml`.
3. Validate `docker compose config` parses.
4. Build images locally: `docker compose build hermes-gateway hermes-dashboard`.
5. Update `dashboard/services_catalog.py` health probe.
6. Rebuild dashboard image.
7. Bring up new services: `docker compose up -d hermes-gateway hermes-dashboard`.
8. Verify healthchecks green, Discord bot online, web UI reachable, Ordo dashboard tile green.
9. Add `tests/test_hermes_docker.py`.
10. Delete `scripts/start-hermes-host.sh` + `tests/test_start_hermes_host.py`.
11. Rewrite `docs/hermes-agent.md`.
12. Strip host-mode vars from `.env.example`.
13. Add CHANGELOG entry.
14. Final verification sweep + code review.
15. Merge to main.

## Testing

### Static tests (`tests/test_hermes_docker.py`)

- `docker-compose.yml` defines both services.
- Each service's image build context is `./hermes`.
- `hermes-dashboard` publishes port 9119 via `${HERMES_DASHBOARD_PORT:-9119}:9119`.
- Both services mount `${BASE_PATH}:/workspace` and `${DATA_PATH}/hermes:/home/hermes/.hermes`.
- `dashboard/services_catalog.py` Hermes entry uses `http://hermes-dashboard:9119/` (not `host.docker.internal`).
- `hermes/Dockerfile` has expected `FROM` lines for both stages.
- `hermes/entrypoint.sh` has a `#!/usr/bin/env bash` shebang and `exec "$@"` tail.

### Integration smoke (not in CI — operator runs)

- `docker compose up -d --build` completes without error.
- `docker compose ps hermes-gateway hermes-dashboard` shows both `(healthy)`.
- `curl -sf http://localhost:9119/` returns Hermes web UI HTML.
- `curl -sf http://localhost:8080/api/health` shows `{"id":"hermes","ok":true}`.
- Discord bot online in operator's server (user allowlist still applies).
- `docker compose logs hermes-gateway` shows `✓ discord connected`.

## Risks

1. **First build is slow** (~3-5 min): Python deps + npm install + vite build + git clone. Cached after first build; subsequent builds use Docker layer cache unless the pinned SHA changes. Mitigation: not a mitigation needed — just set expectations.
2. **Image size** (~900MB-1.2GB): Hermes has heavy ML dependencies (whisper, transformers, sentence-transformers). Multi-stage keeps Node out of runtime. Not unusual for this stack.
3. **Config migration race**: entrypoint seeds keys only when missing, so existing config (from phase-1 host mode) survives. But if a key exists with a stale value (e.g. `model.base_url=http://localhost:11435/v1` from host mode), it stays — and is wrong for the Docker network (localhost → model-gateway). Plan will include a one-time manual step to wipe the host-mode model config keys so the entrypoint reseeds them correctly, or use `key-absent-or-stale` logic in the entrypoint. Prefer the latter: entrypoint checks that `model.base_url` contains `model-gateway:11435` (Docker DNS) and rewrites if not.
4. **Windows Docker Desktop bind-mount performance**: `BASE_PATH:/workspace` on Windows is slower than a native volume for high-I/O paths. Hermes doesn't do high-I/O in the repo — it reads on demand — so not a practical concern.
5. **Port 9119 collision**: if the operator still has a host-mode `hermes dashboard` running, the compose service will fail to publish 9119. Mitigation: plan's operator-cleanup note tells the user to kill leftover host-mode processes before the first `docker compose up -d`.
6. **Web UI crash loop**: if the Node build fails mid-Dockerfile, both services fail to build. Mitigation: cross-check by building the web UI standalone in the plan's step 4 so any upstream JS issues surface early.
7. **HERMES_PINNED_SHA no longer env-overridable**: lives in Dockerfile now. Small papercut for version-testing. Mitigation: accept it; Docker build args can still override via `docker compose build --build-arg HERMES_PINNED_SHA=<other>`.

## Verification contract

After merge, this must all be true:

```bash
# 1. Compose parses
docker compose config >/dev/null 2>&1 && echo OK

# 2. Both services listed
docker compose config --services | grep -E "^hermes-(gateway|dashboard)$" | wc -l
# Expected: 2

# 3. Fresh up-d works
docker compose up -d hermes-gateway hermes-dashboard
sleep 30
docker compose ps hermes-gateway hermes-dashboard | grep -c "healthy"
# Expected: 2

# 4. Dashboard integration
curl -sf http://localhost:8080/api/health | grep -o '"id":"hermes","ok":true'

# 5. Web UI
curl -sf http://localhost:9119/ | head -c 200 | grep -i "hermes"

# 6. Zero host-mode residue
test ! -f scripts/start-hermes-host.sh
test ! -f tests/test_start_hermes_host.py

# 7. Tests pass
python -m pytest tests/test_hermes_docker.py -v
```
